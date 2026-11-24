# -*- coding: utf-8 -*-
"""下课后已登录学生会话立即失效回归（2026-10-23）。"""
import uuid

from app import create_app
from app.blueprints.auth import invalidate_active_class_cache
from app.extensions import db
from app.models import AttendanceRecord, Class, ClassroomSession, Student

CSRF = 't'


def _session_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s['csrf_token'] = CSRF
    return client


def test_student_session_invalidated_when_class_stops():
    sfx = uuid.uuid4().hex[:8]
    class_name = f'__end_class_{sfx}'
    number = f'__end_class_stu_{sfx}'
    app = create_app()
    cls_id = None
    stu_id = None
    try:
        with app.app_context():
            cls = Class(name=class_name)
            stu = Student(name='下课后学生', student_number=number,
                          student_class=class_name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, stu])
            db.session.flush()
            stu.class_id = cls.id
            db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
            db.session.commit()
            cls_id, stu_id = cls.id, stu.id
            invalidate_active_class_cache()

        # 真实 API 登录会写入 classroom_bound 标记
        student = _session_client(app)
        resp = student.post('/api/auth/login', json={
            'student_number': number, 'password': 'pass123456',
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200
        assert student.get('/api/auth/status').get_json()['data']['student_id'] == stu_id

        admin = app.test_client()
        with admin.session_transaction() as s:
            s['is_admin'] = True
            s['admin_name'] = '管理员'
            s['csrf_token'] = CSRF
        stop = admin.post('/admin/classroom/session/stop',
                          data={'csrf_token': CSRF, 'class_id': str(cls_id)},
                          headers={'X-CSRFToken': CSRF})
        assert stop.status_code in (301, 302)

        status = student.get('/api/auth/status').get_json()['data']
        assert status['student_id'] is None
    finally:
        with app.app_context():
            if cls_id is not None:
                ClassroomSession.query.filter_by(class_id=cls_id).delete(
                    synchronize_session=False)
            if stu_id is not None:
                AttendanceRecord.query.filter_by(student_id=stu_id).delete(
                    synchronize_session=False)
            Student.query.filter_by(student_number=number).delete(
                synchronize_session=False)
            Class.query.filter_by(name=class_name).delete(synchronize_session=False)
            db.session.commit()
            invalidate_active_class_cache()
