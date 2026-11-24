# -*- coding: utf-8 -*-
"""2026-09-10 全面审查修复回归测试

覆盖本轮修复（详见 git show 8d47f69:docs/全面审查报告-2026-09-10.md）：
- P1   私有上传目录点段穿越（cloud_drive/5/../6）授权绕过 → 403
- P1   课件目录 show=false 的点段绕过 → 403
- P2   填空题标准答案含 '//'（如 https://...）逐字作答被判 0 → 判满分
- P2   单选题大小写/全角答案误判（'b' vs 'B'、'Ｂ' vs 'B'）
- P2   综合题父题分值强制 = 子题之和（批量挂题辅助函数口径）
- P2   批量挂题 link_questions_to_exam_bulk 幂等 + 位次唯一
- P2   批量网盘容量 set_drive_quota_mb_bulk 去重 + 单次提交
- P3   小组设置端点拒绝外班组长
- P3   /study/link 反斜杠 URL（开放框架/钓鱼跳转）→ 400
- P2   AI 流式并发全进程上限（线程池保护闸门）
"""
import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, Exam, ExamQuestion, Question, Student,
                        StudentDriveQuota, StudyGroup,
                        link_questions_to_exam_bulk)
from app.services.scoring_service import (score_fill, score_single,
                                          _parse_acceptable_answers)
from app.services.student_drive_service import set_drive_quota_mb_bulk
from app.utils import has_dot_segment

CSRF = 'rev0910-csrf'
CLS_NAME = '审查0910班'
CLS2_NAME = '审查0910乙班'
STU_NUM = 'REV0910A'
STU2_NUM = 'REV0910B'
EXAM_NAME = '审查0910试卷'
GROUP_NAME = '0910组'


class _Q:
    """轻量题目替身（仅评分函数所需字段）。"""

    def __init__(self, answer, score, question_type='fill'):
        self.answer = answer
        self.score = score
        self.question_type = question_type


# ── 点段穿越清单单元测试 ──────────────────────────────
@pytest.mark.parametrize('path,expected', [
    ('/static/uploads/cloud_drive/5/../6/x.pdf', True),
    ('/static/uploads/cloud_drive/5/%2e%2e/6/x.pdf', True),
    ('/static/uploads/python_files/../python_answers/x.py', True),
    ('/static/uploads/cloud_drive/5/./x.pdf', True),
    ('/static/uploads/drive/2/..\\3/x.pdf', True),
    ('/static/uploads/cloud_drive/5/file.pdf', False),
    ('/static/uploads/drive/2/a.b.c.pdf', False),
    ('/static/uploads/cloud_drive/5/sub/dir/x.pdf', False),
])
def test_has_dot_segment(path, expected):
    assert has_dot_segment(path) is expected


# ── 评分口径 ──────────────────────────────────────────
def test_fill_answer_containing_slashes_scores_full():
    """标准答案为 URL 时，逐字作答必须判满分（此前被 '//' 拆解误判 0）。"""
    q = _Q('https://www.python.org', 10)
    assert score_fill(q, 'https://www.python.org') == 10.0
    # 多解语义仍保留：仅主机名同样给分
    assert score_fill(q, 'www.python.org') == 10.0
    # 错误答案仍不得分
    assert score_fill(q, 'www.python.orgg') == 0.0


def test_fill_multi_solution_with_spaces():
    q = _Q('money // m', 10)
    assert score_fill(q, 'money') == 10.0
    assert score_fill(q, 'm') == 10.0


def test_parse_acceptable_keeps_literal():
    acc = _parse_acceptable_answers('https://a.b/c', _Q('', 1))
    assert 'https://a.b/c' in acc


def test_single_choice_case_and_fullwidth():
    q = _Q('b', 5, 'single')
    assert score_single(q, 'B') == 5
    assert score_single(q, 'Ｂ') == 5          # 全角
    assert score_single(q, 'a') == 0
    # 中文选项文本不接受大小写归并，仍按原样比较
    q2 = _Q('计算机', 5, 'single')
    assert score_single(q2, '计算机') == 5
    assert score_single(q2, '网络') == 0


# ── 批量挂题/容量辅助函数 ─────────────────────────────
@pytest.fixture(scope='module')
def app():
    application = create_app()
    _seed(application)
    yield application
    with application.app_context():
        _cleanup()


def _cleanup():
    conn = db.session.connection()
    conn.execute(db.text(
        'DELETE FROM exam_question WHERE exam_id IN '
        '(SELECT id FROM exam WHERE name=:n)'), {'n': EXAM_NAME})
    conn.execute(db.text(
        'DELETE FROM question WHERE exam_id IN '
        '(SELECT id FROM exam WHERE name=:n)'), {'n': EXAM_NAME})
    conn.execute(db.text('DELETE FROM exam WHERE name=:n'), {'n': EXAM_NAME})
    conn.execute(db.text(
        'DELETE FROM student_drive_quota WHERE student_id IN '
        '(SELECT id FROM student WHERE student_number IN (:a,:b))'),
        {'a': STU_NUM, 'b': STU2_NUM})
    conn.execute(db.text(
        'DELETE FROM study_group WHERE name=:n'), {'n': GROUP_NAME})
    conn.execute(db.text(
        'DELETE FROM student WHERE student_number IN (:a,:b)'),
        {'a': STU_NUM, 'b': STU2_NUM})
    conn.execute(db.text('DELETE FROM classes WHERE name IN (:a,:b)'),
                 {'a': CLS_NAME, 'b': CLS2_NAME})
    # 必须提交：session.connection() 开启事务，会话销毁时未提交即回滚。
    # 本函数自 2026-09-10 起一直缺这一行，清理**从未生效**——每跑一次
    # 这套件就往生产库留下 2 班 + 2 生 + 1 组 + 1 卷（2026-09-13 审查发现）。
    # 放在函数内而非调用处，避免后续新增调用方再忘。
    db.session.commit()


def _seed(app):
    with app.app_context():
        for name in (CLS_NAME, CLS2_NAME):
            if not Class.query.filter_by(name=name).first():
                db.session.add(Class(name=name))
        db.session.commit()
        cls1 = Class.query.filter_by(name=CLS_NAME).first()
        cls2 = Class.query.filter_by(name=CLS2_NAME).first()
        for num, name, cid in ((STU_NUM, '审查0910学生A', cls1.id),
                               (STU2_NUM, '审查0910学生B', cls2.id)):
            stu = Student.query.filter_by(student_number=num).first()
            if not stu:
                stu = Student(name=name, student_number=num,
                              student_class=cls1.name if cid == cls1.id
                              else cls2.name,
                              class_id=cid, is_activated=True,
                              has_changed_password=True)
                stu.set_password('Rev0910#')
                db.session.add(stu)
        group = StudyGroup.query.filter_by(name=GROUP_NAME).first()
        if not group:
            db.session.add(StudyGroup(name=GROUP_NAME, class_id=cls1.id))
        db.session.commit()


def _ids(app):
    with app.app_context():
        s1 = Student.query.filter_by(student_number=STU_NUM).first()
        s2 = Student.query.filter_by(student_number=STU2_NUM).first()
        return s1.id, s2.id


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = CSRF
    return client


def _student_client(app, sid):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['student_name'] = '审查0910学生A'
        s['csrf_token'] = CSRF
    return client


def _make_exam(app):
    with app.app_context():
        exam = Exam.query.filter_by(name=EXAM_NAME).first()
        if exam:
            return exam.id
        exam = Exam(name=EXAM_NAME, is_active=True, is_visible=True,
                    is_enabled=True, duration=30)
        db.session.add(exam)
        db.session.flush()
        qids = []
        for i in range(3):
            q = Question(exam_id=exam.id, question_type='single',
                         content=f'0910题{i}', options='A|B|C|D',
                         answer='A', score=5)
            db.session.add(q)
            qids.append(q)
        db.session.commit()
        return exam.id


def test_bulk_link_idempotent_and_unique_positions(app):
    with app.app_context():
        eid = _make_exam(app)
        qids = [q.id for q in Question.query.filter_by(exam_id=eid).all()]
        # 先清空已有挂载，构造干净场景
        ExamQuestion.query.filter_by(exam_id=eid).delete()
        db.session.commit()
        added = link_questions_to_exam_bulk(qids, eid)
        assert added == len(qids)
        # 重复调用幂等：不再新增
        assert link_questions_to_exam_bulk(qids, eid) == 0
        rows = ExamQuestion.query.filter_by(exam_id=eid).all()
        assert len(rows) == len(qids)
        positions = [r.position for r in rows]
        assert len(set(positions)) == len(positions)
        assert min(positions) >= 1


def test_bulk_quota_dedupes_and_persists(app):
    with app.app_context():
        s1, s2 = _ids(app)
        StudentDriveQuota.query.filter(
            StudentDriveQuota.student_id.in_([s1, s2])).delete(
            synchronize_session=False)
        db.session.commit()
        n = set_drive_quota_mb_bulk([s1, s2, s1], 123)
        assert n == 2
        rows = StudentDriveQuota.query.filter(
            StudentDriveQuota.student_id.in_([s1, s2])).all()
        assert len(rows) == 2
        assert all(r.quota_mb == 123 for r in rows)
        # 二次调用为更新而非新增
        set_drive_quota_mb_bulk([s1, s2], 456)
        rows = StudentDriveQuota.query.filter(
            StudentDriveQuota.student_id.in_([s1, s2])).all()
        assert len(rows) == 2
        assert all(r.quota_mb == 456 for r in rows)


# ── 穿越防护（集成） ──────────────────────────────────
def test_private_upload_traversal_blocked(app):
    """学生用 .. 折叠路径读取他人目录 → 403（而非 200/404）。"""
    s1, s2 = _ids(app)
    client = _student_client(app, s1)
    for path in (
        f'/static/uploads/cloud_drive/{s1}/../{s2}/secret.pdf',
        f'/static/uploads/cloud_drive/{s1}/%2e%2e/{s2}/secret.pdf',
        '/static/uploads/python_files/../python_answers/x.py',
        f'/static/uploads/drive/{s1}/../{s2}/x.pdf',
    ):
        resp = client.get(path)
        assert resp.status_code == 403, f'{path} -> {resp.status_code}'
    # 正常同 id 路径仍放行（鉴权逻辑未被误伤；文件不存在时为 404）
    resp = client.get(f'/static/uploads/cloud_drive/{s1}/nope.pdf')
    assert resp.status_code == 404


def test_courseware_traversal_blocked(app):
    """课件目录点段穿越 → 403（未登录也拒绝）。"""
    client = app.test_client()
    resp = client.get('/static/uploads/someRes/../otherRes/file.pdf')
    assert resp.status_code == 403


# ── 小组长跨班校验 ────────────────────────────────────
def test_group_settings_rejects_cross_class_leader(app):
    s1, s2 = _ids(app)
    with app.app_context():
        group = StudyGroup.query.filter_by(name=GROUP_NAME).first()
        gid = group.id
        group.leader_id = None
        db.session.commit()
    client = _admin_client(app)
    resp = client.post(
        f'/admin/groups/{gid}/drive-settings',
        data={'leader_id': str(s2), 'csrf_token': CSRF},
        follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        group = db.session.get(StudyGroup, gid)
        assert group.leader_id is None, '外班学生不得被设为组长'
        s2_row = db.session.get(Student, s2)
        assert s2_row.group_id != gid, '外班学生不得被并入本组'


# ── 外链页 URL 校验 ───────────────────────────────────
@pytest.mark.parametrize('raw', [
    '/\\evil.example.com',
    '/%5Cevil.example.com'.replace('%5C', '\\'),
])
def test_study_link_rejects_backslash(app, raw):
    client = _admin_client(app)
    resp = client.get('/study/link', query_string={'url': raw})
    assert resp.status_code == 400


def test_study_link_accepts_relative(app):
    client = _admin_client(app)
    resp = client.get('/study/link', query_string={'url': '/static/x.html'})
    assert resp.status_code == 200


# ── AI 流式并发闸门 ───────────────────────────────────
def test_ai_global_stream_cap(app):
    import app.blueprints.ai as ai_mod
    with app.test_request_context('/api/ai/chat/stream'):
        ai_mod._stream_count.clear()
        acquired = 0
        # 全局上限内的请求应全部拿到名额（每用户上限 2 需绕开：用不同 actor）
        for i in range(40):
            if ai_mod._acquire_stream_slot(f'actor{i}'):
                acquired += 1
        limit = ai_mod._global_stream_limit()
        assert 0 < limit <= 40
        assert acquired == limit, f'acquired={acquired} limit={limit}'
        ai_mod._stream_count.clear()


def test_ai_per_user_stream_cap(app):
    import app.blueprints.ai as ai_mod
    with app.test_request_context('/api/ai/chat/stream'):
        ai_mod._stream_count.clear()
        assert ai_mod._acquire_stream_slot('same') is True
        assert ai_mod._acquire_stream_slot('same') is True
        assert ai_mod._acquire_stream_slot('same') is False
        ai_mod._stream_count.clear()
