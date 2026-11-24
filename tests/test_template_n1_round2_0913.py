# -*- coding: utf-8 -*-
"""模板懒加载 N+1 第二轮：关系预取回归（补 2026-09-13 审查报告 §8.1，原文 git show 8d47f69:docs/全面审查报告-2026-09-13.md）

`§8.1` 修了 3 处（考试页、学生小组右侧卡片、优秀作品页）后，又对全部 71 个
模板做了一轮「循环内关系访问 × 视图预取」普查，确认以下真缺口并逐一钉住。
**每例都是增量口径**（预热 → 量基准行 → 再加 8 行同类数据 → 再量），因为
这类缺陷的特征正是「查询数随行数线性增长」：

| 页面 | 模板每行访问 | 修复前增量 |
|---|---|---|
| `/teacher/works` | `a.resource.title` | +8 |
| `/admin/works/activity/<id>` | `w.evaluation` | +8 |
| `/admin/groups` | `g.members`、`g.files`（集合） | +16 |
| `/admin/trend/<id>` | `question.sub_questions`（集合） | +8 |
| `/admin/statistics` | `student.class_.name` | +8 |
| `/groups` | `req.student.name` | +8 |
| `/online_exam/<id>` | `question.sub_questions`（集合） | +8 |
| `/result/<id>` | 同上 | +8 |

三个设计要点，都是踩过坑才定下来的：

1. **先预热再量基准**。首请求要填 `recent_exams`／`get_classes_cached` 等 TTL
   缓存，把它算进基准会让增量凭空少 1（实测 `/teacher/works` 因此从 4 掉到 3）。
2. **新增行的关联对象必须各不相同**（每个新增学生各占一个新班级）。many-to-one
   懒加载默认走 `use_get`：目标已在 identity map 里就**不发 SQL**，同一批学生
   同班时增量会塌成 1，测不出缺陷。
3. **每例都带「行确实渲染了」的守卫断言**，否则页面把行过滤掉时会以增量 0
   通过（假绿）。

阈值 `≤ 3`：修复后增量应为 0，留 3 条余量吸收 TTL 缓存恰好在两次测量之间
过期。红检时最低增量 8，远高于阈值。

**被否掉的候选**：`/admin/student-drive` 的 `s.class_`。该视图自己就跑了
`Class.query.order_by(Class.name).all()`（模板要用班级下拉框），全部班级已在
identity map 里，逐行 `s.class_` 恒命中、不发 SQL——原候选是脚本层面的误报，
按「脚本报出的问题先怀疑脚本」的约定未改动代码。`/admin/works/activity` 的
`w.student.class_` 同型（该视图亦加载了全部班级），故只对真正逐行的
`w.evaluation` 做预取。

**会写生产库**（1 班起、每例最多 10 名学生的班级 + 资源/活动 + 试卷/综合题/
小题 + 成绩 + 小组/网盘文件/入组申请 + 开考记录），按前缀定向清理（含
`log`），跑完须复跑 `tools/review_db_residue_check.py` 确认零残留。
"""
import contextlib
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import (Class, Exam, GroupFile, GroupJoinRequest,
                        LearningActivity, Question, Resource, Result, Student,
                        StudentWork, StudyGroup, SubQuestion, WorkEvaluation)

CLASS_NAME = '审查0913N1班'
STU_NUM = '0913N1'
STU_NAME = '0913N1生'
EXAM_NAME = '审查0913N1卷'
ACT_TITLE = '审查0913N1活动'
RES_TITLE = '审查0913N1资源'
GRP_NAME = '0913N1组'
_CSRF = 'C' * 32
_COUNTED = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
IDS = {}


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture(autouse=True)
def _isolated(app):
    _purge(app)
    _seed(app)   # 每例独立重建基准数据（增量口径要求起点一致）
    yield
    _purge(app)


@contextlib.contextmanager
def _query_counter(engine):
    """统计 SELECT/INSERT/UPDATE/DELETE 条数。

    只认这四类开头：事务控制语句（BEGIN/COMMIT/SAVEPOINT）在不同驱动/
    连接复用状态下条数会浮动，计入会让增量口径不稳。
    """
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
    """按本模块命名前缀定向清理（child → parent），函数内 commit。"""
    p_exam = {'p': EXAM_NAME + '%'}
    p_stu = {'p': STU_NUM + '%'}
    p_grp = {'p': GRP_NAME + '%'}
    p_act = {'p': ACT_TITLE + '%'}
    p_res = {'p': RES_TITLE + '%'}
    with app.app_context():
        s = db.session
        # 试卷侧
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
            'DELETE FROM sub_question WHERE question_id IN '
            '(SELECT id FROM question WHERE exam_id IN '
            ' (SELECT id FROM exam WHERE name LIKE :p))'), p_exam)
        s.execute(db.text(
            'DELETE FROM question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text('DELETE FROM exam WHERE name LIKE :p'), p_exam)
        # 作品侧（评价是作品的子行，先删）
        s.execute(db.text(
            'DELETE FROM work_evaluation WHERE work_id IN '
            '(SELECT id FROM student_work WHERE student_id IN '
            ' (SELECT id FROM student WHERE student_number LIKE :p))'), p_stu)
        s.execute(db.text(
            'DELETE FROM student_work WHERE student_id IN '
            '(SELECT id FROM student WHERE student_number LIKE :p)'), p_stu)
        # 小组侧
        s.execute(db.text(
            'DELETE FROM group_file WHERE group_id IN '
            '(SELECT id FROM study_group WHERE name LIKE :p)'), p_grp)
        s.execute(db.text(
            'DELETE FROM group_join_request WHERE student_id IN '
            '(SELECT id FROM student WHERE student_number LIKE :p)'), p_stu)
        # student.group_id 与 study_group.leader_id 互为外键，先双向解绑
        s.execute(db.text(
            'UPDATE student SET group_id = NULL WHERE student_number LIKE :p'),
            p_stu)
        s.execute(db.text(
            'UPDATE study_group SET leader_id = NULL WHERE name LIKE :p'),
            p_grp)
        s.execute(db.text('DELETE FROM study_group WHERE name LIKE :p'), p_grp)
        s.execute(db.text('DELETE FROM student WHERE student_number LIKE :p'),
                  p_stu)
        s.execute(db.text('DELETE FROM classes WHERE name LIKE :p'),
                  {'p': CLASS_NAME + '%'})
        s.execute(db.text(
            'DELETE FROM learning_activity WHERE title LIKE :p'), p_act)
        s.execute(db.text('DELETE FROM resource WHERE title LIKE :p'), p_res)
        for lit in (EXAM_NAME, CLASS_NAME, STU_NUM, STU_NAME,
                    ACT_TITLE, RES_TITLE, GRP_NAME):
            s.execute(db.text('DELETE FROM log WHERE detail LIKE :p'),
                      {'p': '%' + lit + '%'})
        s.commit()


def _client(app, role):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.clear()
        sess['csrf_token'] = _CSRF
        sess.permanent = True
        if role == 'admin':
            sess['is_admin'] = True
        elif role == 'student':       # 生1：已有考试结果（结果页用）
            sess['student_id'] = IDS['student1']
        else:                          # 生2：无结果无开考记录（考试页用）
            sess['student_id'] = IDS['student2']
    return client


def _count(app, url, role):
    client = _client(app, role)
    # db.engine 是 LocalProxy，必须在 app_context 内解析（否则 RuntimeError）
    with app.app_context():
        eng = db.engine
    with _query_counter(eng) as n:
        r = client.get(url)
    assert r.status_code == 200, f'{url}（{role}）返回 {r.status_code}'
    return n(), r.get_data(as_text=True)


def _seed(app):
    """基准数据：1 班 2 生、1 资源 1 活动、1 卷 1 综合题 1 小题、1 成绩、
    1 小组（含 1 成员 + 1 网盘文件）、1 条入组申请。"""
    with app.app_context():
        s = db.session
        cls = Class(name=CLASS_NAME)
        s.add(cls)
        s.commit()
        cid = cls.id

        stu1 = Student(name=STU_NAME + '1', student_number=STU_NUM + '1',
                       class_id=cid, student_class=CLASS_NAME,
                       is_activated=True, has_changed_password=True)
        stu2 = Student(name=STU_NAME + '2', student_number=STU_NUM + '2',
                       class_id=cid, student_class=CLASS_NAME,
                       is_activated=True, has_changed_password=True)
        for st in (stu1, stu2):
            st.set_password('Test@0913')
            s.add(st)
        s.commit()
        stu1_id, stu2_id = stu1.id, stu2.id

        res = Resource(title=RES_TITLE + '1', url='/uploads/n1.html')
        s.add(res)
        s.commit()
        act = LearningActivity(resource_id=res.id, title=ACT_TITLE + '1',
                               is_active=True)
        s.add(act)
        s.commit()
        act_id = act.id

        exam = Exam(name=EXAM_NAME, is_active=True, is_visible=True, duration=30)
        s.add(exam)
        s.flush()
        q = Question(exam_id=exam.id, question_type='comprehensive',
                     content='综合题', answer='', score=10)
        s.add(q)
        s.commit()
        qid = q.id
        s.add(SubQuestion(question_id=qid, question_type='single',
                          content='小题1', answer='A', score=10, order=1))
        work = StudentWork(activity_id=act_id, student_id=stu1_id,
                           title='作品1', work_type='text',
                           text_content='x', status='submitted')
        s.add(work)
        s.flush()
        s.add(WorkEvaluation(work_id=work.id, score=90.0, grade='A'))

        grp = StudyGroup(name=GRP_NAME + '1', class_id=cid, leader_id=stu1_id)
        s.add(grp)
        s.commit()
        stu1.group_id = grp.id
        s.add(GroupFile(group_id=grp.id, uploader_id=stu1_id,
                        filename='f1.txt', original_filename='f1.txt',
                        file_size=100, file_path='drive/n1_f1.txt'))
        s.add(GroupJoinRequest(student_id=stu2_id, group_id=grp.id,
                               request_type='join', status='pending'))

        base = datetime.now() - timedelta(hours=1)
        s.add(Result(student_id=stu1_id, exam_id=exam.id,
                     answers=json.dumps({}), scores=json.dumps({}),
                     total_score=0.0, grading_status='auto_graded',
                     submit_time=base))
        s.commit()

        IDS.clear()
        IDS.update({'class1': cid, 'exam1': exam.id, 'activity1': act_id,
                    'group1': grp.id, 'student1': stu1_id,
                    'student2': stu2_id})


def _add(app, kind, n=8):
    """追加 n 行同类数据，返回它们在页面上会渲染出的标识列表。

    新增学生编号从 3 起（基准已用 1、2），且**每人各占一个新班级**：many-to-one
    懒加载走 use_get 时，目标已在 identity map 里就直接命中不发 SQL，同班学生
    会把增量塌成 1，测不出缺陷（见模块 docstring 要点 2）。
    """
    with app.app_context():
        s = db.session
        cid = IDS['class1']
        marks = []
        if kind == 'activity':
            for i in range(2, 2 + n):
                res = Resource(title=RES_TITLE + str(i), url='/uploads/n1.html')
                s.add(res)
                s.commit()
                s.add(LearningActivity(resource_id=res.id,
                                       title=ACT_TITLE + str(i), is_active=True))
                marks.append(ACT_TITLE + str(i))
        elif kind in ('work', 'group', 'student', 'result', 'request'):
            stu_ids = []
            for i in range(3, 3 + n):
                c = Class(name=CLASS_NAME + str(i))
                s.add(c)
                s.flush()
                st = Student(name=STU_NAME + str(i),
                             student_number=STU_NUM + str(i), class_id=c.id,
                             student_class=c.name, is_activated=True,
                             has_changed_password=True)
                st.set_password('Test@0913')
                s.add(st)
                s.flush()
                stu_ids.append(st.id)
                marks.append(STU_NAME + str(i))
            if kind == 'work':
                for i, sid in zip(range(2, 2 + n), stu_ids):
                    w = StudentWork(activity_id=IDS['activity1'], student_id=sid,
                                    title='作品' + str(i), work_type='text',
                                    text_content='x', status='submitted')
                    s.add(w)
                    s.flush()
                    s.add(WorkEvaluation(work_id=w.id, score=float(60 + i),
                                         grade='B'))
            elif kind == 'group':
                for i, sid in zip(range(2, 2 + n), stu_ids):
                    g = StudyGroup(name=GRP_NAME + str(i), class_id=cid,
                                   leader_id=sid)
                    s.add(g)
                    s.flush()
                    s.add(GroupFile(group_id=g.id, uploader_id=sid,
                                    filename='f%d.txt' % i,
                                    original_filename='f%d.txt' % i,
                                    file_size=100,
                                    file_path='drive/n1_f%d.txt' % i))
                    s.execute(db.text(
                        'UPDATE student SET group_id = :g WHERE id = :s'),
                        {'g': g.id, 's': sid})
            elif kind == 'result':
                base = datetime.now()
                for i, sid in enumerate(stu_ids):
                    s.add(Result(student_id=sid, exam_id=IDS['exam1'],
                                 answers=json.dumps({}), scores=json.dumps({}),
                                 total_score=0.0, grading_status='auto_graded',
                                 submit_time=base + timedelta(minutes=i)))
            elif kind == 'request':
                for sid in stu_ids:
                    s.add(GroupJoinRequest(student_id=sid,
                                           group_id=IDS['group1'],
                                           request_type='join',
                                           status='pending'))
        elif kind == 'question':
            for i in range(2, 2 + n):
                q = Question(exam_id=IDS['exam1'], question_type='comprehensive',
                             content='综合题' + str(i), answer='', score=10)
                s.add(q)
                s.flush()
                s.add(SubQuestion(question_id=q.id,
                                  question_type='single',
                                  content='小题%d' % i, answer='A', score=10,
                                  order=1))
                marks.append('第%d题' % i)
        s.commit()
        return marks


def _delta(app, url, role, kind, base_marker, grown_marker, n=8):
    """预热 → 基准行查询数 → 追加 n 行 → 再量，返回两次之差。

    预热不可省：首请求要填 TTL 缓存（见模块 docstring 要点 1）。
    两处守卫断言：基准行与新增行都必须在页面上真的渲染出来，否则「页面把行
    过滤掉了」会以增量 0 通过，测试假绿。
    """
    _client(app, role).get(url)          # 预热（丢弃结果，只为填缓存）
    base_n, base_html = _count(app, url, role)
    assert base_marker in base_html, (
        f'{url} 未渲染基准行 {base_marker}，本用例失去意义')
    _add(app, kind, n)
    grown_n, grown_html = _count(app, url, role)
    assert grown_marker in grown_html, (
        f'{url} 未渲染新增行 {grown_marker}，增量口径不可信')
    return grown_n - base_n


# 阈值：修复后应恒为 0；留余量吸收 TTL 缓存恰好在两次测量之间过期。
# 红检时最低增量 8，仍会报红。
_MAX_DELTA = 3


def test_teacher_works_prefetch_resource(app):
    """`/teacher/works`：每行 a.resource.title（活动数分页 20/页）"""
    d = _delta(app, '/teacher/works', 'admin', 'activity',
               ACT_TITLE + '1', ACT_TITLE + '9')
    assert d <= _MAX_DELTA, (
        f'增加 8 个活动后多了 {d} 条查询：LearningActivity.resource 未预取')


def test_works_activity_prefetch_evaluation(app):
    """`/admin/works/activity/<id>`：每行 w.evaluation

    （`w.student.class_` 不在此列：该视图已 Class.query.all()，全部班级在
    identity map 里，逐行访问不发 SQL——普查脚本的误报。）
    """
    d = _delta(app, f"/admin/works/activity/{IDS['activity1']}", 'admin', 'work',
               STU_NAME + '1', STU_NAME + '10')
    assert d <= _MAX_DELTA, (
        f'增加 8 件作品后多了 {d} 条查询：StudentWork.evaluation 未预取')


def test_admin_groups_prefetch_members_and_files(app):
    """`/admin/groups`：每小组 g.members（含整行学生）+ g.files"""
    d = _delta(app, f"/admin/groups?class_id={IDS['class1']}", 'admin', 'group',
               GRP_NAME + '1', GRP_NAME + '9')
    assert d <= _MAX_DELTA, (
        f'增加 8 个小组后多了 {d} 条查询：StudyGroup 的 members / files 未预取')


def test_trend_page_prefetch_sub_questions(app):
    """`/admin/trend/<id>`：表头遍历 question.sub_questions

    视图已按 IN 批量查过小题，但结果只进了统计用的 subs_by_q；必须用
    set_committed_value 回填——直接赋值会为维护 backref 先加载旧集合，N+1
    只是从模板挪到赋值行。
    """
    d = _delta(app, f"/admin/trend/{IDS['exam1']}", 'admin', 'question',
               '第1题', '第9题')
    assert d <= _MAX_DELTA, (
        f'增加 8 道综合题后多了 {d} 条查询：subs_by_q 未真正回填 question.'
        'sub_questions（批量预取白做）')


def test_statistics_prefetch_student_class(app):
    """`/admin/statistics?exam_id=`：成绩表每行 student.class_.name

    该页班级走 get_classes_cached()（SimpleNamespace，不进 identity map），
    故逐行 class_ 是真查询；每个学生各占一班时增量 = 行数。
    """
    d = _delta(app, f"/admin/statistics?exam_id={IDS['exam1']}", 'admin',
               'result', STU_NAME + '1', STU_NAME + '10')
    assert d <= _MAX_DELTA, (
        f'增加 8 条成绩后多了 {d} 条查询：students_map 未预取 class_')


def test_student_groups_prefetch_request_student(app):
    """`/groups`：每条入组申请 req.student.name / student_number（不分页）"""
    d = _delta(app, '/groups', 'student', 'request',
               STU_NAME + '2', STU_NAME + '10')
    assert d <= _MAX_DELTA, (
        f'增加 8 条入组申请后多了 {d} 条查询：GroupJoinRequest.student 未预取')


def test_online_exam_page_prefetch_sub_questions(app):
    """`/online_exam/<id>`：学生开考页每道综合题的 sub_questions

    热点路径——每名学生每次开考都要过一遍。预热那次请求会创建开考记录
    （写库），把这笔写算进基准会掩盖读数。
    """
    d = _delta(app, f"/online_exam/{IDS['exam1']}", 'student2', 'question',
               '小题1', '小题9')
    assert d <= _MAX_DELTA, (
        f'增加 8 道综合题后开考页多了 {d} 条查询：subs_by_q 未真正回填'
        '（用了会触发旧集合加载的直接赋值，而非 set_committed_value）')


def test_result_page_prefetch_sub_questions(app):
    """`/result/<id>`：成绩回看页每道综合题的 sub_questions（同上）"""
    with app.app_context():
        rid = Result.query.filter_by(student_id=IDS['student1'],
                                     exam_id=IDS['exam1']).first().id
    d = _delta(app, f'/result/{rid}', 'student', 'question', '小题1', '小题9')
    assert d <= _MAX_DELTA, (
        f'增加 8 道综合题后回看页多了 {d} 条查询：subs_by_q 未真正回填'
        '（用了会触发旧集合加载的直接赋值，而非 set_committed_value）')
