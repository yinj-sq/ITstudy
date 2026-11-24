"""交卷 is_visible 门控回归测试

回归对象：online_exam.submit_exam 对不可见试卷的校验。
此前缺陷：对所有人校验 is_visible，考试中管理员隐藏试卷后，
在考学生交卷 403、收卷自动提交同样被拒 → 答卷永久丢失。
修复后：仅拒绝"从未开考"的学生；有开考记录的学生始终可交卷。
"""
import pytest

from app import create_app
from app.extensions import db
from app.models import Exam, Student, ExamAttempt, Result, Log
from datetime import datetime

_CSRF = 'test-csrf-token'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    # 清理测试数据（防御性，正常路径测试内已清理）
    with app.app_context():
        Result.query.filter_by(student_id=None).delete(synchronize_session=False)
        ExamAttempt.query.filter_by(student_id=None).delete(synchronize_session=False)
        Exam.query.filter(Exam.name == '__回归测试__').delete(synchronize_session=False)
        Student.query.filter(Student.student_number.like('REG-%')).delete(synchronize_session=False)
        db.session.commit()


def _make_student(app, number):
    with app.app_context():
        stu = Student(name=f'回归学生{number}', student_number=f'REG-{number}')
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        return stu.id


def _make_exam(app, **kw):
    with app.app_context():
        exam = Exam(name='__回归测试__', **kw)
        db.session.add(exam)
        db.session.commit()
        return exam.id


def _make_attempt(app, student_id, exam_id):
    with app.app_context():
        attempt = ExamAttempt(student_id=student_id, exam_id=exam_id,
                              start_time=datetime.now())
        db.session.add(attempt)
        db.session.commit()


def _cleanup(app, stu_ids, exam_id):
    with app.app_context():
        if stu_ids:
            # log 不在下面的外键链上：交卷会写一条 user_type='student' 的
            # 操作日志，不单独清就会留下"已删学生的提交记录"悬空审计行
            Log.query.filter(Log.user_type == 'student',
                             Log.user_id.in_(stu_ids)).delete(
                synchronize_session=False)
            Result.query.filter(Result.student_id.in_(stu_ids)).delete(synchronize_session=False)
            ExamAttempt.query.filter(ExamAttempt.student_id.in_(stu_ids)).delete(
                synchronize_session=False)
            Student.query.filter(Student.id.in_(stu_ids)).delete(synchronize_session=False)
        if exam_id:
            Exam.query.filter_by(id=exam_id).delete(synchronize_session=False)
        db.session.commit()


def _login(app, student_id):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['student_id'] = student_id
        sess['student_name'] = '回归学生'
        sess['student_class_id'] = None
        sess['csrf_token'] = _CSRF
        sess.permanent = True
    return client


def test_hidden_exam_ongoing_student_can_submit(app):
    """核心回归：考试被隐藏（is_visible=False）时，已开考学生仍可交卷。"""
    stu = _make_student(app, 'H1')
    exam = _make_exam(app, is_visible=False, is_active=False,
                      is_enabled=False, is_collected=True)
    _make_attempt(app, stu, exam)
    try:
        client = _login(app, stu)
        resp = client.post(f'/submit_exam/{exam}',
                           json={}, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 200, f'在考学生交卷被拒: {resp.status_code} {resp.get_data(as_text=True)[:200]}'
        data = resp.get_json()
        assert data.get('success') is True, f'响应异常: {data}'
    finally:
        _cleanup(app, [stu], exam)


def test_hidden_exam_never_started_student_rejected(app):
    """从未开考的学生提交不可见试卷仍应被拒绝（保持原有防护）。"""
    stu = _make_student(app, 'H2')
    exam = _make_exam(app, is_visible=False, is_collected=True)
    try:
        client = _login(app, stu)
        resp = client.post(f'/submit_exam/{exam}',
                           json={}, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 403
        assert resp.get_json()['message'] == '试卷不可访问'
    finally:
        _cleanup(app, [stu], exam)


def test_visible_exam_never_started_student_rejected(app):
    """未开考 + 未收卷 + 可见 → 原有"请先开始考试"行为不被破坏。"""
    stu = _make_student(app, 'H3')
    exam = _make_exam(app, is_visible=True, is_collected=False)
    try:
        client = _login(app, stu)
        resp = client.post(f'/submit_exam/{exam}',
                           json={}, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 403
        assert resp.get_json()['message'] == '请先开始考试'
    finally:
        _cleanup(app, [stu], exam)
