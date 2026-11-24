# -*- coding: utf-8 -*-
"""课堂大屏手工设置班级防呆回归（2026-11-04）。

现场反馈：管理员手工设置上课班级后，刷新/脚本访问课堂大屏即变回“未设置”。
根因：开启「课程表自动切换班级」时，非作息时段访问大屏会执行自动同步，
目标班级集合为空 → 手工设置的班级被自动停用并清空。

修复：
- 非作息时段保存设置且勾选自动切换 → 自动关闭自动切换并提示；
- 大屏在自动切换开启但不在作息时段时显示醒目预警；
- 手工设置的班级不再被随后的自动同步清空。
"""
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, ClassroomSession
from app.blueprints import classroom as classroom_module

CSRF = 'classroom-manual-switch-csrf'


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
    data.setdefault('csrf_token', CSRF)
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def _setting_snapshot():
    setting = classroom_module._get_classroom_setting()
    return {
        'active_class_id': setting.active_class_id,
        'current_schedule_id': setting.current_schedule_id,
        'display_message': setting.display_message,
        'seat_offset': setting.seat_offset,
        'auto_switch': setting.auto_switch,
    }


def _setting_restore(snap):
    setting = classroom_module._get_classroom_setting()
    for key, value in snap.items():
        setattr(setting, key, value)
    db.session.commit()


def test_out_of_period_save_auto_disables_auto_switch(app, monkeypatch):
    """非作息时段保存：自动切换被关闭，手工班级保持激活且不被清空。"""
    sfx = uuid.uuid4().hex[:8]
    cls = None
    snap = None
    try:
        with app.app_context():
            snap = _setting_snapshot()
            cls = Class(name=f'__ms_cls_{sfx}')
            db.session.add(cls)
            db.session.commit()
            cid = cls.id
        admin = _client(app, is_admin=True, admin_name='防呆管理员')
        # 模拟“当前不在任何作息时段”
        monkeypatch.setattr(classroom_module, '_auto_period_for_now',
                            lambda *a, **k: None)
        resp = _post(admin, '/admin/classroom/settings', {
            'active_class_id': str(cid), 'current_schedule_id': '',
            'display_message': '防呆测试', 'seat_offset': '0',
            'auto_switch': 'true'})
        assert resp.status_code in (302, 303)
        page = admin.get(f'/admin/classroom?class_id={cid}')
        assert page.status_code == 200
        assert '已自动关闭' in page.get_data(as_text=True)
        with app.app_context():
            setting = classroom_module._get_classroom_setting()
            assert setting.auto_switch is False
            assert setting.active_class_id == cid
            session = ClassroomSession.query.filter_by(
                class_id=cid).first()
            assert session is not None and session.is_active is True
        # 再次访问大屏（自动切换已关闭，不再触发同步）：班级仍为上课中
        page = admin.get(f'/admin/classroom?class_id={cid}')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert f'__ms_cls_{sfx}' in text
        with app.app_context():
            session = ClassroomSession.query.filter_by(
                class_id=cid).first()
            assert session.is_active is True
    finally:
        with app.app_context():
            # 先还原全局设置（active_class_id 外键指向本类时需先解除），
            # 再删除会话与班级
            if snap:
                _setting_restore(snap)
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()


def test_in_period_save_keeps_auto_switch(app, monkeypatch):
    """处于作息时段时保留管理员的自动切换选择。"""
    sfx = uuid.uuid4().hex[:8]
    cls = None
    snap = None
    try:
        with app.app_context():
            snap = _setting_snapshot()
            cls = Class(name=f'__ms_in_{sfx}')
            db.session.add(cls)
            db.session.commit()
            cid = cls.id
        admin = _client(app, is_admin=True, admin_name='防呆管理员')
        # 模拟“当前处于作息时段”（同步本身打桩为空操作，仅验证保存语义）
        monkeypatch.setattr(classroom_module, '_auto_period_for_now',
                            lambda *a, **k: object())
        monkeypatch.setattr(classroom_module, '_sync_auto_sessions',
                            lambda *a, **k: None)
        resp = _post(admin, '/admin/classroom/settings', {
            'active_class_id': str(cid), 'current_schedule_id': '',
            'display_message': '', 'seat_offset': '0',
            'auto_switch': 'true'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            setting = classroom_module._get_classroom_setting()
            assert setting.auto_switch is True
    finally:
        with app.app_context():
            # 先还原全局设置（active_class_id 外键指向本类时需先解除），
            # 再删除会话与班级
            if snap:
                _setting_restore(snap)
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
