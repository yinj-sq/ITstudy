# -*- coding: utf-8 -*-
"""多班课堂大屏与会话回归（2026-10-22）。"""
import datetime
import pathlib
import uuid

from app import create_app
from app.blueprints.auth import invalidate_active_class_cache
from app.extensions import db
from app.models import (AttendanceRecord, Class, ClassroomSession,
                        ClassroomSetting, ClassSchedule, Resource, Schedule,
                        Student, TeachingSession)
from app.utils import invalidate_lookup_cache

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSRF = 't'


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_two_classes_active_and_big_screen_selects_class():
    suffix = uuid.uuid4().hex[:8]
    c1_name = f'__mc_A_{suffix}'
    c2_name = f'__mc_B_{suffix}'
    stu_num = f'__mc_stu_{suffix}'
    stu1_num = f'__mc_stu1_{suffix}'
    app = create_app()
    original_setting = None
    try:
        with app.app_context():
            setting = ClassroomSetting.query.first()
            if setting:
                original_setting = (setting.active_class_id,
                                    setting.current_schedule_id,
                                    setting.display_message,
                                    setting.seat_offset,
                                    setting.auto_switch)
            c1 = Class(name=c1_name, description='多班A')
            c2 = Class(name=c2_name, description='多班B')
            sched = Schedule(period_name='__mc节', start_time='00:00',
                             end_time='23:59', sort_order=1, is_active=True)
            stu = Student(name='多班学生', student_number=stu_num,
                          student_class=c2_name, has_changed_password=True)
            stu1 = Student(name='多班学生一', student_number=stu1_num,
                           student_class=c1_name, has_changed_password=True)
            for item in (stu, stu1):
                item.set_password('pass123456')
            db.session.add_all([c1, c2, sched, stu, stu1])
            db.session.flush()
            c1.id, c2.id  # ids available
            stu.class_id = c2.id
            stu1.class_id = c1.id
            ordered = Schedule.query.filter_by(is_active=True).order_by(
                Schedule.sort_order, Schedule.start_time).all()
            period_no = next(i for i, row in enumerate(ordered, 1)
                             if row.id == sched.id)
            db.session.add_all([
                ClassSchedule(weekday=datetime.datetime.now().weekday() + 1,
                              period_number=period_no, class_name=c1_name),
                ClassSchedule(weekday=datetime.datetime.now().weekday() + 1,
                              period_number=period_no, class_name=c2_name),
            ])
            if setting:
                setting.active_class_id = c1.id
                setting.current_schedule_id = sched.id
                setting.display_message = '多班测试'
                setting.seat_offset = 0
                setting.auto_switch = True
            else:
                setting = ClassroomSetting(active_class_id=c1.id,
                                           current_schedule_id=sched.id,
                                           display_message='多班测试',
                                           auto_switch=True)
                db.session.add(setting)
            db.session.commit()
            c1id, c2id, sched_id = c1.id, c2.id, sched.id
            stuid, stuid1 = stu.id, stu1.id
            invalidate_lookup_cache('schedules')
            invalidate_lookup_cache('classes')
            invalidate_active_class_cache()

        admin = _client(app, is_admin=True, admin_name='多班管理员')
        resp = admin.get(f'/admin/classroom?class_id={c2id}')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert c2_name in html and c1_name in html
        with app.app_context():
            sessions = ClassroomSession.query.filter_by(is_active=True).all()
            assert {c1id, c2id}.issubset({s.class_id for s in sessions})

        status = admin.post('/api/classroom/status', data={
            'csrf_token': CSRF, 'class_id': str(c2id)
        }, headers={'X-CSRFToken': CSRF})
        assert status.status_code == 200
        body = status.get_json()['data']
        assert body['active_class']['id'] == c2id
        assert {c1id, c2id}.issubset(
            {s['class_id'] for s in body['sessions']})

        # 保存某班设置不得清空另一班已登录学生
        with app.app_context():
            s1 = db.session.get(Student, stuid1)
            s1.last_seen = datetime.datetime.now()
            db.session.commit()
        save = admin.post('/admin/classroom/settings', data={
            'csrf_token': CSRF, 'active_class_id': str(c2id),
            'current_schedule_id': str(sched_id), 'display_message': '多班测试',
            'seat_offset': '0', 'auto_switch': 'true'
        }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert save.status_code in (302, 303)
        with app.app_context():
            assert db.session.get(Student, stuid1).last_seen is not None

        # 停用一班只清该班签到，另一班会话保持可用
        stop = admin.post('/admin/classroom/session/stop', data={
            'csrf_token': CSRF, 'class_id': str(c1id)
        }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert stop.status_code in (302, 303)
        with app.app_context():
            assert not ClassroomSession.query.filter_by(
                class_id=c1id).first().is_active
            assert ClassroomSession.query.filter_by(
                class_id=c2id).first().is_active
            assert db.session.get(Student, stuid1).last_seen is None

        # 两个班都处于当前会话，学生即使属于第二个班也能登录
        student = _client(app)
        login = student.post('/', data={
            'csrf_token': CSRF, 'student_number': stu_num,
            'password': 'pass123456'
        }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert login.status_code in (302, 303)
    finally:
        with app.app_context():
            # 先解除全局设置对测试班级/作息时段的引用，否则班级无法删除
            setting = ClassroomSetting.query.first()
            if setting:
                if original_setting:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = original_setting
                else:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
                db.session.flush()
            ClassroomSession.query.filter_by(class_id=c1id).delete(
                synchronize_session=False)
            ClassroomSession.query.filter_by(class_id=c2id).delete(
                synchronize_session=False)
            ClassSchedule.query.filter(ClassSchedule.class_name.in_(
                [c1_name, c2_name])).delete(synchronize_session=False)
            AttendanceRecord.query.filter(
                AttendanceRecord.student_id.in_([stuid, stuid1])).delete(
                synchronize_session=False)
            Student.query.filter(
                Student.student_number.in_([stu_num, stu1_num])).delete(
                synchronize_session=False)
            Class.query.filter(Class.name.in_([c1_name, c2_name])).delete(
                synchronize_session=False)
            Schedule.query.filter_by(id=sched_id).delete(synchronize_session=False)
            db.session.commit()
            invalidate_active_class_cache()


def test_delete_class_keeps_teaching_record():
    """删除班级时教学记录保留，只解除 class_id 外键。"""
    suffix = uuid.uuid4().hex[:8]
    class_name = f'__mc_del_{suffix}'
    app = create_app()
    with app.app_context():
        cls = Class(name=class_name)
        res = Resource(title=f'__mc_res_{suffix}')
        db.session.add_all([cls, res])
        db.session.flush()
        record = TeachingSession(resource_id=res.id, teacher_name='测试教师',
                                 class_id=cls.id)
        db.session.add(record)
        db.session.commit()
        cls_id, res_id, record_id = cls.id, res.id, record.id

    admin = _client(app, is_admin=True, admin_name='多班管理员')
    resp = admin.post(f'/admin/classes/{cls_id}/delete', data={
        'csrf_token': CSRF
    }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
    assert resp.status_code in (302, 303)

    with app.app_context():
        assert db.session.get(Class, cls_id) is None
        assert db.session.get(TeachingSession, record_id).class_id is None
        TeachingSession.query.filter_by(id=record_id).delete(
            synchronize_session=False)
        Resource.query.filter_by(id=res_id).delete(synchronize_session=False)
        db.session.commit()
