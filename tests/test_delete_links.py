"""删除链路回归测试（此前缺陷：子表 FK 无级联未清理 → 删除必 500）

覆盖三条已确认的删除必 500 路径：
1. API 删除资源（有 ResourceQuizResult 引用）
2. API 删除小组（有 GroupJoinRequest 引用）
3. HTML 删除试卷（有 ExamAttempt 残留开考记录）
"""
import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Exam, Student, Class, Resource, ResourceQuizResult, StudyGroup,
    GroupJoinRequest, ExamAttempt, TeachingSession,
)

_CSRF = 'test-csrf-token'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        _cleanup()


def _cleanup():
    """只清本模块自己造的行。

    ⚠️ 这里此前是一句无条件的
    `TRUNCATE resource_quiz_result, teaching_session, group_join_request,
     exam_attempt, study_group, resource, exam, student RESTART IDENTITY
     CASCADE`。当时 tests/ 直连 postgresql.txt 里配置的**生产库**（独立
    测试库 itstudy_test 是 2026-09-13 才由 tests/conftest.py 引入的，见
    2026-09-13 审查报告 §9 #5，原文 git show 8d47f69:docs/全面审查报告-2026-09-13.md）。在只装了测试数据的开发机上
    看着无害，但在装了真实数据的机器上跑一次 pytest，全部试卷、学生、
    资源、小组、开考记录会被清空——而且是静默的。

    三个用例本身都在各自的 finally 里清理自己造的行，模块级 TRUNCATE 纯属
    多余的"扫尾"，却把"测试毁灭生产数据"的风险引进了整个套件；它还顺带
    抹掉了**其它模块**的残留，让此前的残留复查一路误报为"零残留"。
    改为按本模块的命名前缀定向清理（2026-09-13 审查发现并修复）。
    """
    conn = db.session.connection()
    stu = "SELECT id FROM student WHERE student_number LIKE 'DL-%'"
    cls = "SELECT id FROM classes WHERE name='回归班级G1'"
    grp = "SELECT id FROM study_group WHERE name='回归小组G1'"
    res = "SELECT id FROM resource WHERE title='回归资源R1'"
    exm = "SELECT id FROM exam WHERE name='回归试卷E1'"
    # 先子表后主表：以下外键无级联，顺序反了会抛 FK 违约
    for sql in (
        f'DELETE FROM resource_quiz_result WHERE student_id IN ({stu}) '
        f'OR resource_id IN ({res})',
        f'DELETE FROM teaching_session WHERE resource_id IN ({res})',
        f'DELETE FROM group_join_request WHERE student_id IN ({stu}) '
        f'OR group_id IN ({grp})',
        f'DELETE FROM exam_attempt WHERE student_id IN ({stu}) '
        f'OR exam_id IN ({exm})',
        f'DELETE FROM study_group WHERE id IN ({grp})',
        f'DELETE FROM resource WHERE id IN ({res})',
        f'DELETE FROM exam WHERE id IN ({exm})',
        "DELETE FROM student WHERE student_number LIKE 'DL-%'",
        f'DELETE FROM classes WHERE id IN ({cls})',
        # 删资源/删卷都会写操作日志；log 不在上面的外键链上，必须按名字单独清
        "DELETE FROM log WHERE detail LIKE '%回归资源R1%' "
        "OR detail LIKE '%回归试卷E1%' OR detail LIKE '%回归小组G1%'",
    ):
        conn.execute(db.text(sql))
    # 必须提交：session.connection() 开启事务，会话销毁时未提交即回滚
    db.session.commit()


def _mk_student(app, number):
    with app.app_context():
        stu = Student(name=f'删链学生{number}', student_number=f'DL-{number}')
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        return stu.id


def _admin_login(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['csrf_token'] = _CSRF
        sess.permanent = True
    return client


def test_api_delete_resource_with_quiz_results(app):
    """有测验成绩/教学记录引用的资源,API 删除必须成功而非 500。"""
    stu_id = _mk_student(app, 'R1')
    with app.app_context():
        res = Resource(title='回归资源R1', url='/static/uploads/r1/index.html')
        db.session.add(res)
        db.session.commit()
        res_id = res.id
        db.session.add(ResourceQuizResult(student_id=stu_id, resource_id=res_id,
                                          quiz_name='测试测验', total_score=100))
        db.session.add(TeachingSession(resource_id=res_id, teacher_name='回归教师',
                                       start_time=None))
        db.session.commit()
    try:
        client = _admin_login(app)
        resp = client.delete(f'/api/resources/{res_id}',
                             headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()['success'] is True
        with app.app_context():
            assert db.session.get(Resource, res_id) is None
            assert ResourceQuizResult.query.filter_by(resource_id=res_id).count() == 0
            assert TeachingSession.query.filter_by(resource_id=res_id).count() == 0
    finally:
        with app.app_context():
            Resource.query.filter_by(id=res_id).delete(synchronize_session=False)
            ResourceQuizResult.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
            TeachingSession.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()


def test_api_delete_group_with_join_requests(app):
    """有待处理加入/退出申请的小组,API 删除必须成功而非 500。"""
    stu_id = _mk_student(app, 'G1')
    with app.app_context():
        cls = Class(name='回归班级G1')
        db.session.add(cls)
        db.session.commit()
        group = StudyGroup(name='回归小组G1', class_id=cls.id)
        db.session.add(group)
        db.session.commit()
        group_id = group.id
        db.session.add(GroupJoinRequest(student_id=stu_id, group_id=group_id,
                                        request_type='join', status='pending'))
        db.session.commit()
    try:
        client = _admin_login(app)
        resp = client.delete(f'/api/groups/{group_id}',
                             headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()['success'] is True
        with app.app_context():
            assert db.session.get(StudyGroup, group_id) is None
            assert GroupJoinRequest.query.filter_by(group_id=group_id).count() == 0
    finally:
        with app.app_context():
            StudyGroup.query.filter_by(id=group_id).delete(synchronize_session=False)
            GroupJoinRequest.query.filter_by(group_id=group_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()


def test_html_delete_exam_with_attempts(app):
    """在考拦截 + FK 清理双语义：
    ① 存在开考记录（=考试进行中）时 HTML 删卷必须被拒绝（与 API 版
       api_exams.delete_exam 同口径），答卷不可被管理员侧删空；
    ② 无开考记录的试卷删除必须成功而非 500，且兜底清理不残留。"""
    stu_id = _mk_student(app, 'E1')
    with app.app_context():
        exam = Exam(name='回归试卷E1')
        db.session.add(exam)
        db.session.commit()
        exam_id = exam.id
        db.session.add(ExamAttempt(student_id=stu_id, exam_id=exam_id))
        db.session.commit()
    try:
        client = _admin_login(app)
        # ① 在考拦截：删除被拒，试卷与开考记录均保留
        resp = client.post(f'/admin/exams/delete/{exam_id}',
                           data={}, headers={'X-CSRFToken': _CSRF},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert '无法删除' in resp.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(Exam, exam_id) is not None
            assert ExamAttempt.query.filter_by(exam_id=exam_id).count() == 1
        # ② 开考记录清除后：删除成功（FK 兜底清理路径回归）
        with app.app_context():
            ExamAttempt.query.filter_by(exam_id=exam_id).delete(
                synchronize_session=False)
            db.session.commit()
        resp = client.post(f'/admin/exams/delete/{exam_id}',
                           data={}, headers={'X-CSRFToken': _CSRF},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert '删除成功' in resp.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(Exam, exam_id) is None
            assert ExamAttempt.query.filter_by(exam_id=exam_id).count() == 0
    finally:
        with app.app_context():
            Exam.query.filter_by(id=exam_id).delete(synchronize_session=False)
            ExamAttempt.query.filter_by(exam_id=exam_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()
