# -*- coding: utf-8 -*-
"""教师两种登录模式查看/设置课堂大屏回归（2026-10-22）。"""
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import (Class, ClassroomSession, ClassroomSetting, SystemConfig,
                        Teacher, teacher_class)

CSRF = 't'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None):
    data = dict(data or {})
    data['csrf_token'] = CSRF
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def test_legacy_session_created_even_when_other_class_session_exists(app):
    """旧单班设置迁移不能因为“已有其他班级会话”而跳过。"""
    suffix = uuid.uuid4().hex[:8]
    a_name = f'__tcr_legacy_A_{suffix}'
    b_name = f'__tcr_legacy_B_{suffix}'
    setting_saved = None
    setting_id = None
    ids = {}
    try:
        with app.app_context():
            cls_a = Class(name=a_name)
            cls_b = Class(name=b_name)
            db.session.add_all([cls_a, cls_b])
            db.session.flush()
            ids.update(a=cls_a.id, b=cls_b.id)
            # 另一班级已有历史会话（停用），旧实现会因此跳过迁移
            db.session.add(ClassroomSession(class_id=cls_b.id, is_active=False))
            setting = ClassroomSetting.query.first()
            if setting:
                setting_id = setting.id
                setting_saved = (setting.active_class_id, setting.current_schedule_id,
                                 setting.display_message, setting.seat_offset,
                                 setting.auto_switch)
                setting.active_class_id = cls_a.id
            else:
                setting = ClassroomSetting(active_class_id=cls_a.id)
                db.session.add(setting)
                db.session.flush()
                setting_id = setting.id
            db.session.commit()

        admin = _client(app, is_admin=True, admin_name='管理员')
        assert admin.get('/admin/classroom').status_code == 200
        with app.app_context():
            migrated = ClassroomSession.query.filter_by(
                class_id=ids['a']).first()
            assert migrated is not None and migrated.is_active is True
    finally:
        with app.app_context():
            ClassroomSession.query.filter(
                ClassroomSession.class_id.in_([ids.get('a'), ids.get('b')])
            ).delete(synchronize_session=False)
            setting = db.session.get(ClassroomSetting, setting_id) if setting_id else None
            if setting:
                if setting_saved:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = setting_saved
                else:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
                db.session.flush()
            Class.query.filter(Class.name.in_([a_name, b_name])).delete(
                synchronize_session=False)
            db.session.commit()


def test_teacher_both_modes_can_view_and_set_only_own_classroom(app):
    suffix = uuid.uuid4().hex[:8]
    a_name = f'__tcr_A_{suffix}'
    b_name = f'__tcr_B_{suffix}'
    teacher_name = f'__tcr_t_{suffix}'
    old_code = None
    setting_id = None
    setting_saved = None
    setting_created = False
    ids = {}
    try:
        with app.app_context():
            cls_a = Class(name=a_name)
            cls_b = Class(name=b_name)
            teacher = Teacher(username=teacher_name, display_name='教室教师')
            teacher.set_password('pass123456')
            teacher.classes = [cls_a]
            db.session.add_all([cls_a, cls_b, teacher])
            db.session.flush()
            ids.update(a=cls_a.id, b=cls_b.id, t=teacher.id)
            db.session.add_all([
                ClassroomSession(class_id=cls_a.id, display_message='A班课堂',
                                 seat_offset=0, is_active=True),
                ClassroomSession(class_id=cls_b.id, display_message='B班课堂',
                                 seat_offset=0, is_active=True),
            ])
            setting = ClassroomSetting.query.first()
            if setting:
                setting_id = setting.id
                setting_saved = (setting.active_class_id, setting.current_schedule_id,
                                 setting.display_message, setting.seat_offset,
                                 setting.auto_switch)
                setting.active_class_id = cls_b.id
                setting.display_message = '全局默认'
            else:
                setting = ClassroomSetting(active_class_id=cls_b.id,
                                           display_message='全局默认')
                db.session.add(setting)
                db.session.flush()
                setting_created = True
                setting_id = setting.id
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            code_hash = generate_password_hash('readonly123', method='pbkdf2:sha256')
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
            db.session.commit()
            from app.utils import password_fingerprint
            code_fp = password_fingerprint(code_hash)

        edit = _client(app, is_teacher=True, teacher_id=ids['t'],
                       teacher_name='教室教师', teacher_mode='edit')
        page = edit.get('/admin/classroom')
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert a_name in html and b_name not in html
        assert edit.get(f'/admin/classroom?class_id={ids["b"]}').status_code == 403

        status = edit.post('/api/classroom/status', data={
            'csrf_token': CSRF, 'class_id': str(ids['a'])
        }, headers={'X-CSRFToken': CSRF}).get_json()
        assert status['success'] is True
        assert status['data']['active_class']['id'] == ids['a']
        assert {s['class_id'] for s in status['data']['sessions']} == {ids['a']}
        denied = edit.post('/api/classroom/status', data={
            'csrf_token': CSRF, 'class_id': str(ids['b'])
        }, headers={'X-CSRFToken': CSRF})
        assert denied.status_code == 403

        # 只读模式同样能打开大屏并保存设置（全局默认班级保持不变）
        readonly = _client(app, is_teacher=True, teacher_id=ids['t'],
                           teacher_name='教室教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        assert readonly.get('/admin/classroom').status_code == 200
        resp = _post(readonly, '/admin/classroom/settings', {
            'active_class_id': str(ids['a']), 'current_schedule_id': '',
            'display_message': '只读教师设置', 'seat_offset': '3',
        })
        assert resp.status_code in (302, 303)
        assert f'class_id={ids["a"]}' in resp.headers.get('Location', '')
        with app.app_context():
            session_a = ClassroomSession.query.filter_by(class_id=ids['a']).first()
            assert session_a.display_message == '只读教师设置'
            assert session_a.seat_offset == 3
            assert db.session.get(ClassroomSetting, setting_id).active_class_id == ids['b']

        # 不能设置其他班级
        resp = _post(edit, '/admin/classroom/settings', {
            'active_class_id': str(ids['b']), 'display_message': '越权',
        })
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert ClassroomSession.query.filter_by(
                class_id=ids['b']).first().display_message == 'B班课堂'

        # 新的一课/停用也只作用于本人班级
        resp = _post(edit, '/admin/classroom/new_session', {'class_id': str(ids['b'])})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert ClassroomSession.query.filter_by(
                class_id=ids['b']).first().is_active is True
        resp = _post(edit, '/admin/classroom/session/stop', {'class_id': str(ids['a'])})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert ClassroomSession.query.filter_by(
                class_id=ids['a']).first().is_active is False
            assert ClassroomSession.query.filter_by(
                class_id=ids['b']).first().is_active is True
    finally:
        with app.app_context():
            ClassroomSession.query.filter(
                ClassroomSession.class_id.in_([ids.get('a'), ids.get('b')])
            ).delete(synchronize_session=False)
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == ids.get('t')))
            Teacher.query.filter_by(username=teacher_name).delete(synchronize_session=False)
            # 先解除/还原 ClassroomSetting 对测试班级的引用，再删班级
            setting = db.session.get(ClassroomSetting, setting_id) if setting_id else None
            if setting:
                if setting_created:
                    db.session.delete(setting)
                elif setting_saved:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = setting_saved
                else:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
                db.session.flush()
            Class.query.filter(Class.name.in_([a_name, b_name])).delete(
                synchronize_session=False)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()
