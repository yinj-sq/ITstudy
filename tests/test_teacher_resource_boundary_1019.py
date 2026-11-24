# -*- coding: utf-8 -*-
"""教师端课堂资源边界回归（2026-10-19 教师端实测发现）。

列表页按 show_in_classroom 过滤，但活动/作品详情路由此前只校验教师登录：
教师知道资源 ID 即可直接查看/编辑课堂隐藏资源的活动与学生作品。
"""
import pathlib
import uuid

from app import create_app
from app.extensions import db
from app.models import (Class, ClassroomSetting, LearningActivity, Resource,
                        Student, StudentWork, Teacher)
from app.utils import password_fingerprint


def test_teacher_nav_has_grading_entry():
    src = (pathlib.Path(__file__).resolve().parent.parent / 'templates' /
           'base.html').read_text(encoding='utf-8')
    assert 'href="/admin/grading"' in src
    assert '批改中心' in src


def test_teacher_cannot_reach_hidden_classroom_resource_activity():
    app = create_app()
    class_name = '教师边界回归班'
    hidden_title = '教师边界隐藏资源'
    activity_title = '教师边界隐藏活动'
    with app.app_context():
        setting = ClassroomSetting.query.first()
        original = None
        if setting:
            original = (setting.active_class_id, setting.current_schedule_id,
                        setting.display_message, setting.seat_offset,
                        setting.auto_switch)
        cls = Class(name=class_name, description='教师边界回归')
        db.session.add(cls)
        db.session.flush()
        teacher = Teacher(username='教师边界回归账号', display_name='教师边界回归')
        teacher.set_password('teacher-pass')
        db.session.add(teacher)
        db.session.flush()
        student = Student(name='教师边界回归学生', student_number='教师边界回归学生',
                          student_class=class_name, class_id=cls.id,
                          has_changed_password=True)
        student.set_password('student-pass')
        db.session.add(student)
        db.session.flush()
        resource = Resource(title=hidden_title, url='', show_in_student=True,
                            show_in_classroom=False)
        db.session.add(resource)
        db.session.flush()
        activity = LearningActivity(resource_id=resource.id, title=activity_title,
                                    require_upload=True, is_active=True)
        db.session.add(activity)
        db.session.flush()
        work = StudentWork(activity_id=activity.id, student_id=student.id,
                           title=activity_title, text_content='隐藏作品',
                           public_token=uuid.uuid4().hex)
        db.session.add(work)
        if setting:
            setting.active_class_id = cls.id
        else:
            setting = ClassroomSetting(active_class_id=cls.id)
            db.session.add(setting)
        db.session.commit()
        tid = teacher.id
        fingerprint = password_fingerprint(teacher.password_hash)
        rid, aid, wid = resource.id, activity.id, work.id

    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['is_teacher'] = True
            sess['teacher_id'] = tid
            sess['teacher_name'] = '教师边界回归'
            sess['pwd_fp'] = fingerprint
            sess['csrf_token'] = 't'

        r = client.get(f'/teacher/resources/{rid}/activities', follow_redirects=False)
        assert r.status_code == 302, r.status_code
        assert '/teacher/resources' in r.headers.get('Location', '')

        r = client.get('/teacher/works')
        assert r.status_code == 200
        assert activity_title not in r.get_data(as_text=True)

        r = client.get(f'/teacher/works/activity/{aid}', follow_redirects=False)
        assert r.status_code == 302, r.status_code
        assert '/teacher/works' in r.headers.get('Location', '')

        r = client.get(f'/teacher/works/evaluate/{wid}', follow_redirects=False)
        assert r.status_code == 302, r.status_code
        assert '/teacher/works' in r.headers.get('Location', '')
    finally:
        with app.app_context():
            setting = ClassroomSetting.query.first()
            if setting:
                if original:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = original
                else:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
                db.session.flush()
            db.session.query(StudentWork).filter_by(activity_id=aid).delete(
                synchronize_session=False)
            db.session.query(LearningActivity).filter_by(id=aid).delete(
                synchronize_session=False)
            db.session.query(Resource).filter_by(id=rid).delete(
                synchronize_session=False)
            db.session.query(Student).filter_by(student_number='教师边界回归学生').delete(
                synchronize_session=False)
            db.session.query(Teacher).filter_by(username='教师边界回归账号').delete(
                synchronize_session=False)
            db.session.query(Class).filter_by(name=class_name).delete(
                synchronize_session=False)
            db.session.commit()
