# -*- coding: utf-8 -*-
"""AI 页面图片理解回归：视觉开关、多模态消息与不支持提示（2026-10-23）。"""
import uuid

import pytest

from app import create_app
from app.blueprints import ai as ai_mod
from app.blueprints.ai import _prepare_chat_context
from app.extensions import db
from app.models import AIConfig, AIChatMessage, Class, Student

PNG_DATA_URL = ('data:image/png;base64,'
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
                '+A8AAQUBAScY42YAAAAASUVORK5CYII=')


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = 't'
    return client


def _setup(app, vision):
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        cfg = AIConfig.query.first()
        created = cfg is None
        if created:
            cfg = AIConfig()
            db.session.add(cfg)
        saved = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                 cfg._api_key, cfg.vision_enabled)
        cfg.enabled, cfg.config_mode = True, 'admin'
        cfg.api_url, cfg.model = 'https://api.example.com/v1', 'vision-model'
        cfg.api_key = 'sk-vision-test'
        cfg.vision_enabled = vision
        cls = Class(name=f'__vis_cls_{suffix}')
        stu = Student(name='视觉学生', student_number=f'__vis_{suffix}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.commit()
        return cfg.id if not created else None, created, saved, cls.id, stu.id


def _cleanup(app, created, saved, cls_id, stu_id):
    with app.app_context():
        AIChatMessage.query.filter_by(student_id=stu_id).delete(
            synchronize_session=False)
        Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
        Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
        cfg = AIConfig.query.first()
        if cfg is not None:
            if created:
                db.session.delete(cfg)
            else:
                (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                 cfg._api_key, cfg.vision_enabled) = saved
        db.session.commit()


def test_vision_message_builds_multimodal_content_and_status(app):
    cfg_id, created, saved, cls_id, stu_id = _setup(app, True)
    try:
        with app.test_request_context('/api/ai/chat', method='POST',
                                      json={'message': '这张图讲什么',
                                            'page_content': '',
                                            'images': [PNG_DATA_URL]}):
            from flask import session as flask_session
            flask_session['student_id'] = stu_id
            conv, err = _prepare_chat_context()
            assert err is None and conv is not None
            last = conv['messages'][-1]
            assert isinstance(last['content'], list)
            assert last['content'][0]['type'] == 'text'
            assert last['content'][1]['type'] == 'image_url'
            assert last['content'][1]['image_url']['url'].startswith(
                'data:image/png;base64,')
        c = _client(app, student_id=stu_id, student_name='视觉学生',
                    has_changed_password=True)
        assert c.get('/api/ai/status').get_json()['vision_enabled'] is True
    finally:
        _cleanup(app, created, saved, cls_id, stu_id)


def test_vision_disabled_ignores_images_and_reports_off(app):
    cfg_id, created, saved, cls_id, stu_id = _setup(app, False)
    try:
        with app.test_request_context('/api/ai/chat', method='POST',
                                      json={'message': '这张图讲什么',
                                            'page_content': '',
                                            'images': [PNG_DATA_URL]}):
            from flask import session as flask_session
            flask_session['student_id'] = stu_id
            conv, err = _prepare_chat_context()
            assert err is None and conv is not None
            last = conv['messages'][-1]
            assert isinstance(last['content'], str)
        c = _client(app, student_id=stu_id, student_name='视觉学生',
                    has_changed_password=True)
        assert c.get('/api/ai/status').get_json()['vision_enabled'] is False
    finally:
        _cleanup(app, created, saved, cls_id, stu_id)


def test_admin_vision_switch_visible_and_saved(app):
    cfg_id, created, saved, cls_id, stu_id = _setup(app, False)
    try:
        admin = _client(app, is_admin=True, admin_name='管理员')
        html = admin.get('/admin/ai_config').get_data(as_text=True)
        assert 'visionEnabledSwitch' in html
        resp = admin.post('/admin/ai_config/save',
                          json={'vision_enabled': True},
                          headers={'X-CSRFToken': 't'})
        assert resp.status_code == 200 and resp.get_json()['success'] is True
        with app.app_context():
            assert AIConfig.query.first().vision_enabled is True
    finally:
        _cleanup(app, created, saved, cls_id, stu_id)


def test_auto_image_intent_classifier(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(ai_mod, '_image_config', lambda: SimpleNamespace(
        enabled=True, auto_intent=True))
    monkeypatch.setattr(ai_mod, '_image_capability', lambda: True)
    monkeypatch.setattr(ai_mod, '_resolve_image_config', lambda: (True, {
        'api_url': 'https://image.example.com/v1', 'api_key': 'sk-image',
        'model': 'gpt-image-1', 'size': '1024x1024', 'quality': '',
        'timeout': 30, 'max_images': 1}, 200))
    conv = {'provider': 'openai', 'api_key': 'sk-chat',
            'api_url': 'https://api.example.com/v1', 'model': 'chat-model',
            'message': '请画一只在黑板前讲课的机器人', 'page_content': '',
            'needs_dns_pinning': False}
    monkeypatch.setattr(ai_mod, '_call_chat', lambda *a, **k: (
        True, '{"image":true,"prompt":"机器人老师，扁平插画","summary":"正在生成"}',
        200, 'stop', None))
    result = ai_mod._classify_image_intent(conv)
    assert result is not None
    assert result[1] == '机器人老师，扁平插画'
    monkeypatch.setattr(ai_mod, '_call_chat', lambda *a, **k: (
        True, '{"image":false}', 200, 'stop', None))
    assert ai_mod._classify_image_intent(conv) is None

