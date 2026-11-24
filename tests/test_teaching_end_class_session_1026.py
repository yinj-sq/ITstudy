# -*- coding: utf-8 -*-
"""教师“下课”结束最后一个教学记录时，同步结束班级课堂会话。"""
import uuid
from datetime import datetime

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Class, ClassroomSession, ClassroomSetting, Resource, Student, Teacher,
    TeachingSession, teacher_class,
)

CSRF = 'endclass-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def test_end_class_stops_last_classroom_session(app):
    sfx = uuid.uuid4().hex[:8]
    cls_name = f'__endcls_{sfx}'
    teacher_name = f'__endcls_t_{sfx}'
    stu_num = f'__endcls_s_{sfx}'
    title = f'__endcls_res_{sfx}'
    rid = tid = cid = sid = None
    try:
        with app.app_context():
            cls = Class(name=cls_name)
            teacher = Teacher(username=teacher_name, display_name='下课教师')
            teacher.set_password('pass123456')
            student = Student(name='下课学生', student_number=stu_num,
                              student_class=cls_name, has_changed_password=True)
            student.set_password('pass123456')
            res = Resource(title=title, url='https://example.com/endcls',
                           show_in_student=True, show_in_classroom=True,
                           quiz_mode='none')
            db.session.add_all([cls, teacher, student, res])
            db.session.flush()
            student.class_id = cls.id
            teacher.classes = [cls]
            db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
            setting = ClassroomSetting.query.first()
            if setting is None:
                setting = ClassroomSetting()
                db.session.add(setting)
            setting.active_class_id = cls.id
            db.session.add(TeachingSession(
                resource_id=res.id, teacher_id=teacher.id,
                teacher_name='下课教师', class_id=cls.id,
                status='active', start_time=datetime.now()))
            db.session.commit()
            rid, tid, cid, sid = res.id, teacher.id, cls.id, student.id

        teacher_client = app.test_client()
        with teacher_client.session_transaction() as s:
            s.update(is_teacher=True, teacher_id=tid,
                     teacher_name='下课教师', teacher_mode='edit',
                     csrf_token=CSRF)
        student_client = app.test_client()
        with student_client.session_transaction() as s:
            s.update(student_id=sid, student_name='下课学生',
                     student_class_id=cid, classroom_bound=True,
                     csrf_token=CSRF)
        assert student_client.get('/study').status_code == 200
        resp = teacher_client.post(
            f'/teaching-center/end_class/{rid}',
            data={'class_id': str(cid), 'csrf_token': CSRF},
            follow_redirects=False)
        assert resp.status_code in (302, 303)
        with app.app_context():
            session_row = ClassroomSession.query.filter_by(class_id=cid).first()
            assert session_row is not None and session_row.is_active is False
            setting = ClassroomSetting.query.first()
            assert setting is None or setting.active_class_id != cid
            assert TeachingSession.query.filter_by(
                class_id=cid, end_time=None).count() == 0
        student_client.get('/study')
        with student_client.session_transaction() as s:
            assert not s.get('student_id')
    finally:
        with app.app_context():
            if cid is not None:
                TeachingSession.query.filter_by(class_id=cid).delete(
                    synchronize_session=False)
                ClassroomSession.query.filter_by(class_id=cid).delete(
                    synchronize_session=False)
            if tid is not None:
                db.session.execute(teacher_class.delete().where(
                    teacher_class.c.teacher_id == tid))
            if rid is not None:
                Resource.query.filter_by(id=rid).delete(synchronize_session=False)
            if sid is not None:
                Student.query.filter_by(id=sid).delete(synchronize_session=False)
            ClassroomSetting.query.filter_by(active_class_id=cid).update(
                {ClassroomSetting.active_class_id: None,
                 ClassroomSetting.current_schedule_id: None},
                synchronize_session=False)
            if cid is not None:
                Class.query.filter_by(id=cid).delete(synchronize_session=False)
            if tid is not None:
                Teacher.query.filter_by(id=tid).delete(synchronize_session=False)
            db.session.commit()
