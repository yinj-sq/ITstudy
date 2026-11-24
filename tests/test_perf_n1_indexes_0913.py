# -*- coding: utf-8 -*-
"""性能回归：N+1 消除与索引兜底（2026-09-13 第二轮）

覆盖本轮修复（详见 git show 8d47f69:docs/全面审查报告-2026-09-13.md §8.1）：
- A1  交卷判分不再抛弃已预取的 PythonFile：score_python_file 新增可选
      python_file 参数——传入时 0 次业务 SQL，不传时自行按题反查（后者
      是测试/工具的单题调用路径，得分必须完全一致）
- A2  /exam 不再逐卷懒加载 subject/questions（查询数不随卷数增长）
- A3  /groups 不再逐组懒加载整组学生只为取人数（且人数显示正确）
- A4  /works/excellent 的 joinedload(StudentWork.evaluation) 可构造：
      关系名写错会在**构造期**抛 ArgumentError，页面每次访问都 500
- B1/B3 声明式索引的 raw 兜底：create_all 对已存在表整表跳过，模型里
      写 index=True 等于没写；8 条 ix_* 必须由 create_db_indexes() 建出，
      且重复调用幂等

清理约定：tests/conftest.py 已把整套测试钉在独立库 itstudy_test
（连到生产库直接拒绝运行）。本模块全部数据用前缀常量命名，autouse fixture
在用例前后各清一次（含 log 表与磁盘参考文件），跑完仍须复跑
tools/review_db_residue_check.py 确认零残留。

关于查询计数：只统计 SELECT/INSERT/UPDATE/DELETE，不含 BEGIN/COMMIT/
SAVEPOINT 等事务控制语句——后者随会话状态浮动，会把"少查一次"这类
断言搅成噪声。
"""
import contextlib
import json
import os

import pytest
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import Class, Exam, PythonFile, Question, Student, StudyGroup, Subject

# ── 测试数据命名前缀（tools/review_db_residue_check.py 按这些前缀扫残留）──
EXAM_NAME = '审查0913性能卷'
CLASS_NAME = '审查0913性能班'
GROUP_NAME = '0913PF组'
STU_NUM = '0913PF'
STU_NAME = '0913PF生'

# A1 的题目参考文件（写在 UPLOAD_FOLDER 下，用例结束即删）
REF_FILE_NAME = 'review0913_perf_ref.py'
REF_CONTENT = 'a = ①\nb = ②\nc = ③\n'
STUDENT_OK = 'a = 6\nb = money\nc = money\n'

# B1/B3：模型声明了 index=True 但存量库从未建出的索引（create_db_indexes 兜底）
DECLARED_INDEXES = (
    'ix_group_join_request_student_id',
    'ix_group_join_request_group_id',
    'ix_appeal_student_id',
    'ix_learning_activity_resource_active',
    'ix_question_question_type',
    'ix_study_group_leader_id',
    'ix_group_file_uploader_id',
    'ix_homework_classes_class_id',
)

_COUNTED = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
_TEMP_FILES = []


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture(scope='module')
def engine(app):
    """计数用的引擎句柄（与请求内使用同一实例）。"""
    with app.app_context():
        return db.engine


@pytest.fixture(autouse=True)
def _isolated(app):
    _purge(app)
    yield
    _purge(app)


@contextlib.contextmanager
def _query_counter(engine):
    """统计作用域内的业务 SQL 条数，`with ... as n:` 后取 `n()`。"""
    n = 0

    def _before(conn, cursor, statement, params, context, executemany):
        nonlocal n
        if statement.lstrip().upper().startswith(_COUNTED):
            n += 1

    event.listen(engine, 'before_cursor_execute', _before)
    try:
        yield lambda: n
    finally:
        event.remove(engine, 'before_cursor_execute', _before)


def _purge(app):
    """按本模块命名前缀定向清理，函数内 commit（见模块 docstring）。"""
    for path in _TEMP_FILES:
        try:
            os.remove(path)
        except OSError:
            pass
    _TEMP_FILES.clear()
    p_exam = {'p': EXAM_NAME + '%'}
    p_stu = {'p': STU_NUM + '%'}
    p_group = {'p': GROUP_NAME + '%'}
    with app.app_context():
        s = db.session
        # 子表 → 父表；题库/试卷解耦后 question.exam_id 仅为溯源，仍按卷清
        s.execute(db.text(
            'DELETE FROM result WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM exam_attempt WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM exam_question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM python_file WHERE question_id IN '
            '(SELECT id FROM question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p))'), p_exam)
        s.execute(db.text(
            'DELETE FROM question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text('DELETE FROM exam WHERE name LIKE :p'), p_exam)
        # 学生 ↔ 小组 是双向 FK（student.group_id / study_group.leader_id）：
        # 必须先解引用再删任意一侧，否则外键拒绝
        s.execute(db.text(
            'UPDATE student SET group_id = NULL WHERE student_number LIKE :p'), p_stu)
        s.execute(db.text(
            'UPDATE study_group SET leader_id = NULL WHERE name LIKE :p'), p_group)
        for sql, params in (
            ('DELETE FROM group_join_request WHERE group_id IN '
             '(SELECT id FROM study_group WHERE name LIKE :p)', p_group),
            ('DELETE FROM group_join_request WHERE student_id IN '
             '(SELECT id FROM student WHERE student_number LIKE :p)', p_stu),
            ('DELETE FROM study_group WHERE name LIKE :p', p_group),
            ('DELETE FROM student WHERE student_number LIKE :p', p_stu),
            ('DELETE FROM classes WHERE name LIKE :p', {'p': CLASS_NAME + '%'}),
        ):
            s.execute(db.text(sql), params)
        # log 不挂在任何外键链上，名称扫描查不到——按内容前缀单独清
        for lit in (EXAM_NAME, CLASS_NAME, GROUP_NAME, STU_NUM, STU_NAME):
            s.execute(db.text('DELETE FROM log WHERE detail LIKE :p'),
                      {'p': '%' + lit + '%'})
        s.commit()


def _mk_exam(idx, subject_id=None, qtype='single'):
    """建卷 + 一题（Question 建题时由事件自动挂到 exam_question）。"""
    exam = Exam(name=EXAM_NAME + str(idx), is_active=True, is_visible=True,
                subject_id=subject_id, duration=30)
    db.session.add(exam)
    db.session.flush()
    q = Question(exam_id=exam.id, question_type=qtype, content='性能回归题',
                 answer='A', score=10)
    db.session.add(q)
    db.session.commit()
    return exam, q


def _mk_student(idx, class_id=None):
    s = Student(name=STU_NAME + str(idx), student_number=STU_NUM + str(idx),
                class_id=class_id,
                student_class=CLASS_NAME if class_id else None,
                is_activated=True, has_changed_password=True)
    s.set_password('Test@0913')
    db.session.add(s)
    db.session.commit()
    return s


def _mk_group(idx, class_id):
    g = StudyGroup(name=GROUP_NAME + str(idx), class_id=class_id)
    db.session.add(g)
    db.session.commit()
    return g


def _student_client(app, student_id, class_id=None):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['student_id'] = student_id
        sess['student_name'] = STU_NAME
        sess['student_class_id'] = class_id
        sess['csrf_token'] = 'C' * 32
        sess.permanent = True
    return client


# ── A1：交卷判分复用已预取的参考文件 ──────────────────────

def test_score_python_file_honours_prefetched_reference(app, engine):
    """传入 python_file 时不得再按题反查；不传时行为与得分完全一致。

    原来 submit_exam 已按题批量预取参考文件只喂给 debug 日志，评分函数
    内部又按题反查一遍——预取白做（整班交卷高峰每题一次多余查询）。
    """
    from app.services.scoring_service import score_python_file

    with app.app_context():
        _, q = _mk_exam(9, None, qtype='python_fill')
        q.python_answers = json.dumps({'1': '6', '2': 'money', '3': 'money'})
        abs_path = os.path.join(app.config['UPLOAD_FOLDER'], REF_FILE_NAME)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(REF_CONTENT)
        _TEMP_FILES.append(abs_path)
        db.session.add(PythonFile(question_id=q.id, file_name=REF_FILE_NAME,
                                  file_path=REF_FILE_NAME))
        db.session.commit()
        # commit 会 expire 实例：冷对象的首次属性访问自带一次 SELECT，
        # 会污染下面的计数（这里要测的是评分函数自己发的查询）
        q = db.session.get(Question, q.id)
        pf = PythonFile.query.filter_by(question_id=q.id).first()

        with _query_counter(engine) as n_auto:
            score_auto = score_python_file(q, STUDENT_OK)
        with _query_counter(engine) as n_pre:
            score_pre = score_python_file(q, STUDENT_OK, python_file=pf)

    assert abs(score_auto - 10.0) < 0.01, '自行反查路径得分应为满分'
    assert abs(score_pre - score_auto) < 1e-9, '两条路径得分必须完全一致'
    assert n_auto() == 1, '不传参考文件时应自行反查一次'
    assert n_pre() == 0, '传了参考文件就不得再查（预取被白做的原始缺陷）'


# ── A2：学生考试列表页 ──────────────────────────────

def test_exam_page_queries_do_not_scale_with_exam_count(app, engine):
    """卷数 1 → 5，页面查询数不得跟着涨（懒加载 subject/questions 已消除）。"""
    with app.app_context():
        subject = Subject.query.first()
        subject_id = subject.id if subject else None
        _mk_exam(1, subject_id)
        sid = _mk_student(1).id

    client = _student_client(app, sid)
    client.get('/exam')  # 预热导航/学科缓存，避免把首次填充算进增量

    with _query_counter(engine) as n_one:
        r1 = client.get('/exam')
    assert r1.status_code == 200
    base = n_one()

    with app.app_context():
        for i in range(2, 6):
            _mk_exam(i, subject_id)

    with _query_counter(engine) as n_five:
        r5 = client.get('/exam')
    assert r5.status_code == 200
    grown = n_five()

    # 旧实现每卷各查一次 subject 与整卷题目（+4 卷 = +8 次）
    assert grown - base <= 2, (
        f'查询数随卷数增长：1 卷 {base} 次 → 5 卷 {grown} 次（N+1 回归）')


# ── A3：学生小组页 ──────────────────────────────

def test_groups_page_counts_members_without_per_group_query(app, engine):
    """组数 1 → 5，查询数不得跟着涨；且人数必须显示正确（非只看查询数）。"""
    with app.app_context():
        cls = Class(name=CLASS_NAME)
        db.session.add(cls)
        db.session.commit()
        # 取成裸 int：每次 commit 都会 expire 实例，跨 app_context 再用
        # cls.id 会撞 DetachedInstanceError（上一个会话已随 context 结束）
        cid = cls.id
        me = _mk_student(1, class_id=cid)
        mate = _mk_student(2, class_id=cid)
        g1 = _mk_group(1, cid)
        mate.group_id = g1.id  # 只有 1 组有 1 名组员：模板应显示 1人/0人
        db.session.commit()
        sid = me.id

    client = _student_client(app, sid, class_id=None)
    client.get('/groups')

    with _query_counter(engine) as n_one:
        r1 = client.get('/groups')
    assert r1.status_code == 200
    assert '1人' in r1.get_data(as_text=True), '成员数未渲染（计数改错了）'
    base = n_one()

    with app.app_context():
        for i in range(2, 6):
            _mk_group(i, cid)

    with _query_counter(engine) as n_five:
        r5 = client.get('/groups')
    assert r5.status_code == 200
    html = r5.get_data(as_text=True)
    assert '1人' in html and '0人' in html, '各组成员数显示不正确'
    grown = n_five()

    # 旧实现 `g.members|length` 每组一次查询（+4 组 = +4 次）
    assert grown - base <= 2, (
        f'查询数随组数增长：1 组 {base} 次 → 5 组 {grown} 次（N+1 回归）')


# ── A4：优秀作品页 ──────────────────────────────

def test_excellent_works_joinedload_path_is_valid(app):
    """joinedload 的关系名写错会在构造期抛 ArgumentError → 页面 500。

    作品/活动/评价三级数据链造起来过重，此处只要求空结果下真实构造 SQL
    （查询构造失败即 500，足以覆盖"关系名/加载方向写错"这类缺陷）。
    """
    with app.app_context():
        sid = _mk_student(3).id
    client = _student_client(app, sid)

    r = client.get('/works/excellent')

    assert r.status_code == 200


# ── B1/B3：声明式索引的 raw 兜底 ──────────────────────

def test_declared_indexes_exist_and_creation_is_idempotent(app):
    """8 条 ix_* 必须真实存在于库里，且重复执行 create_db_indexes() 幂等。"""
    with app.app_context():
        if db.engine.dialect.name != 'postgresql':
            pytest.skip('索引存在性断言针对 PostgreSQL（本项目生产库）')
        from app.models import create_db_indexes

        def present():
            params = {f'n{i}': name for i, name in enumerate(DECLARED_INDEXES)}
            holders = ', '.join(f':n{i}' for i in range(len(DECLARED_INDEXES)))
            rows = db.session.execute(db.text(
                'SELECT indexname FROM pg_indexes '
                f'WHERE schemaname = current_schema() AND indexname IN ({holders})'),
                params).fetchall()
            return {r[0] for r in rows}

        missing = set(DECLARED_INDEXES) - present()
        assert not missing, (
            f'模型声明了 index=True 但库里没有：{sorted(missing)}——'
            'create_all 跳过已存在表，必须由 create_db_indexes 兜底')

        create_db_indexes()
        create_db_indexes()  # 幂等：二次调用不报错、不改变索引集合
        assert present() == set(DECLARED_INDEXES)
