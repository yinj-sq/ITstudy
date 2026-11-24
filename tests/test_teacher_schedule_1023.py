# -*- coding: utf-8 -*-
"""教师端作息时间表可见性回归（2026-10-23）。

教师登录编辑模式后落地资源库，此前导航没有作息入口；教师只能进入课堂页
侧栏查看，且没有激活班级时连侧栏也不显示。新增 /teacher/schedule 只读页：
编辑/只读教师、无激活班级时都可查看本人任课班级课程表。
"""
import uuid

from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import Class, ClassSchedule, Schedule, SystemConfig, Teacher
from app.utils import invalidate_lookup_cache, password_fingerprint

CSRF = 't'


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_teacher_schedule_page_visible_without_active_class():
    sfx = uuid.uuid4().hex[:8]
    cls_name = f'__sched_cls_{sfx}'
    t_name = f'__sched_t_{sfx}'
    period = f'测试节次{sfx}'
    app = create_app()
    old_code = ''
    t_id = None
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            cls = Class(name=cls_name)
            teacher = Teacher(username=t_name, display_name='作息教师')
            teacher.set_password('pass123456')
            teacher.classes = [cls]
            db.session.add_all([cls, teacher])
            db.session.flush()
            db.session.add_all([
                Schedule(period_name=period, start_time='08:00',
                         end_time='08:45', sort_order=1, is_active=True),
                ClassSchedule(weekday=1, period_number=1, class_name=cls_name),
            ])
            code_hash = generate_password_hash(
                'readonly123', method='pbkdf2:sha256')
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
            db.session.commit()
            invalidate_lookup_cache('schedules')
            t_id = teacher.id
            code_fp = password_fingerprint(code_hash)

        edit = _client(app, is_teacher=True, teacher_id=t_id,
                       teacher_name='作息教师', teacher_mode='edit')
        resp = edit.get('/teacher/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert period in html and cls_name in html
        nav = edit.get('/teacher/resource-library').get_data(as_text=True)
        assert 'href="/teacher/schedule"' in nav

        readonly = _client(app, is_teacher=True, teacher_id=t_id,
                           teacher_name='作息教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        assert readonly.get('/teacher/schedule').status_code == 200

        admin = _client(app, is_admin=True, admin_name='管理员')
        redirect = admin.get('/teacher/schedule', follow_redirects=False)
        assert redirect.status_code in (301, 302)
        assert '/admin/schedule' in redirect.headers.get('Location', '')
    finally:
        with app.app_context():
            Schedule.query.filter_by(period_name=period).delete(
                synchronize_session=False)
            ClassSchedule.query.filter_by(class_name=cls_name).delete(
                synchronize_session=False)
            db.session.execute(db.text(
                'DELETE FROM teacher_class WHERE teacher_id IN '
                '(SELECT id FROM teacher WHERE username = :u)'), {'u': t_name})
            Teacher.query.filter_by(username=t_name).delete(
                synchronize_session=False)
            Class.query.filter_by(name=cls_name).delete(synchronize_session=False)
            if old_code:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            else:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, '')
            db.session.commit()
            invalidate_lookup_cache('schedules')
