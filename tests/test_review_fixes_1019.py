# -*- coding: utf-8 -*-
"""2026-10-19 审查修复回归：试卷/题目状态机与登录输入上限。

覆盖：
- 已组卷题改“来源卷”时从所有旧卷移出（真实移动，而非追加成多卷）
- 组卷批量提交混入外链题 + 普通题必须整体拒绝
- 考试进行中禁止改时长/改题目（防止卷面与判分口径漂移）
- 管理员登录用户名超长直接拒绝（防超大限流缓存 key）
"""
from datetime import datetime

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (Exam, ExamAttempt, ExamQuestion, Question,
                        Student, link_question_to_exam)

_CSRF = 't'
PREFIX = '1019测试'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    with app.app_context():
        _cleanup()
    yield app
    with app.app_context():
        _cleanup()


def _cleanup():
    conn = db.session.connection()
    conn.execute(text("DELETE FROM result WHERE exam_id IN "
                      "(SELECT id FROM exam WHERE name LIKE :p)"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM exam_attempt WHERE exam_id IN "
                      "(SELECT id FROM exam WHERE name LIKE :p)"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM exam_question WHERE exam_id IN "
                      "(SELECT id FROM exam WHERE name LIKE :p)"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM question WHERE content LIKE :p"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM exam WHERE name LIKE :p"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM student WHERE student_number LIKE :p"),
                 {'p': PREFIX + '%'})
    db.session.commit()


def _login(client):
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF


def _mk_exam(name, duration=30):
    e = Exam(name=name, is_active=True, duration=duration)
    db.session.add(e)
    db.session.flush()
    return e


def _mk_q(content, qtype='single', score=2.0, exam_id=None):
    q = Question(exam_id=exam_id, question_type=qtype, content=content,
                 options='A.1|B.2', answer='A', score=score)
    db.session.add(q)
    db.session.flush()
    return q


def _mk_student(suffix):
    s = Student(name=PREFIX + '学生' + suffix,
                student_number=PREFIX + suffix, is_activated=True)
    db.session.add(s)
    db.session.flush()
    return s


def test_move_question_unlinks_previous_exam(app):
    c = app.test_client()
    _login(c)
    with app.app_context():
        a = _mk_exam(PREFIX + '·A卷')
        b = _mk_exam(PREFIX + '·B卷')
        q = _mk_q(PREFIX + '题·移动')
        db.session.commit()
        link_question_to_exam(q.id, a.id)
        db.session.commit()
        qid, bid = q.id, b.id
        aid = a.id

        resp = c.put(f'/api/questions/{qid}', json={
            'exam_id': bid, 'content': PREFIX + '题·移动（改）',
            'options': 'A.1|B.2', 'answer': 'A', 'score': 2.0
        }, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        linked = {eid for (eid,) in db.session.query(ExamQuestion.exam_id)
                  .filter_by(question_id=qid).all()}
        assert linked == {bid}, linked
        assert aid not in linked


def test_compose_batch_rejects_mixed_link_and_normal(app):
    c = app.test_client()
    _login(c)
    with app.app_context():
        e = _mk_exam(PREFIX + '·混卷')
        q_normal = _mk_q(PREFIX + '题·普通')
        q_link = _mk_q(PREFIX + '题·外链', qtype='link', score=0)
        db.session.commit()
        eid, qn, ql = e.id, q_normal.id, q_link.id

        resp = c.post(f'/admin/exams/{eid}/compose/add',
                      json={'question_ids': [qn, ql]},
                      headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 400, resp.get_data(as_text=True)
        linked = db.session.query(ExamQuestion).filter_by(exam_id=eid).count()
        assert linked == 0


def test_exam_duration_locked_while_attempt_active(app):
    c = app.test_client()
    _login(c)
    with app.app_context():
        e = _mk_exam(PREFIX + '·在考时长', duration=30)
        stu = _mk_student('时长')
        db.session.add(ExamAttempt(student_id=stu.id, exam_id=e.id,
                                   start_time=datetime.now()))
        db.session.commit()
        eid = e.id

        resp = c.put(f'/api/exams/{eid}', json={
            'name': PREFIX + '·在考时长', 'duration': 1
        }, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert db.session.get(Exam, eid).duration == 30


def test_question_edit_locked_while_attempt_active(app):
    c = app.test_client()
    _login(c)
    with app.app_context():
        e = _mk_exam(PREFIX + '·在考题目')
        q = _mk_q(PREFIX + '题·在考', exam_id=e.id)
        stu = _mk_student('题目')
        db.session.add(ExamAttempt(student_id=stu.id, exam_id=e.id,
                                   start_time=datetime.now()))
        db.session.commit()
        qid = q.id

        resp = c.put(f'/api/questions/{qid}', json={
            'exam_id': e.id, 'content': PREFIX + '题·在考（改）',
            'options': 'A.1|B.2', 'answer': 'B', 'score': 2.0
        }, headers={'X-CSRFToken': _CSRF})
        assert resp.status_code == 409, resp.get_data(as_text=True)


def test_admin_login_rejects_overlong_username(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['csrf_token'] = _CSRF
    resp = c.post('/api/auth/admin-login',
                  json={'username': 'a' * 81, 'password': 'x'},
                  headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 400
