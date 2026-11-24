# -*- coding: utf-8 -*-
"""国内 OpenAI 兼容视觉模型预设回归（2026-10-23）。

覆盖 DeepSeek/智谱/MiniMax 当前视觉模型地址与模型名，确认管理端预设
确实渲染、地址/模型名能通过保存校验，并复用现有 image_url 多模态载荷。
"""
import uuid

import pytest

from app import create_app
from app.blueprints.ai import (
    VISION_MODEL_PRESETS, _prepare_chat_context, _valid_api_url,
    _valid_model_name,
)
from app.extensions import db
from app.models import AIConfig, AIChatMessage, Class, Student, Teacher

PNG_DATA_URL = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII='
)
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


def test_domestic_presets_render_and_validate(app):
    admin = _client(app, is_admin=True, admin_name='管理员')
    html = admin.get('/admin/ai_config').get_data(as_text=True)
    assert 'visionPresetSelect' in html and 'applyVisionPreset' in html
    for preset in VISION_MODEL_PRESETS:
        assert preset['model'] in html
        assert preset['api_url'] in html
        assert _valid_api_url(preset['api_url'])
        assert _valid_model_name(preset['model'])
        assert preset['provider'] == 'openai'


def test_domestic_vision_preset_builds_image_url_blocks(app):
    suffix = uuid.uuid4().hex[:8]
    saved = None
    with app.app_context():
        cfg = AIConfig.query.first()
        created = cfg is None
        if created:
            cfg = AIConfig()
            db.session.add(cfg)
        saved = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                 cfg._api_key, cfg.vision_enabled, cfg.provider)
        cfg.enabled = True
        cfg.config_mode = 'admin'
        cfg.provider = 'openai'
        cfg.api_url = 'https://api.deepseek.com'
        cfg.model = 'deepseek-flash'
        cfg.api_key = 'sk-domestic-test'
        cfg.vision_enabled = True
        cls = Class(name=f'__dom_vis_cls_{suffix}')
        stu = Student(name='国内视觉学生', student_number=f'__dom_vis_{suffix}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.commit()
        cls_id, stu_id = cls.id, stu.id
        try:
            with app.test_request_context(
                    '/api/ai/chat', method='POST',
                    json={'message': '请解读这张图片', 'page_content': '',
                          'images': [PNG_DATA_URL]}):
                from flask import session as flask_session
                flask_session['student_id'] = stu_id
                conv, err = _prepare_chat_context()
                assert err is None and conv is not None
                last = conv['messages'][-1]
                assert isinstance(last['content'], list)
                assert last['content'][1]['type'] == 'image_url'
                assert last['content'][1]['image_url']['url'].startswith(
                    'data:image/png;base64,')
                assert conv['api_url'] == 'https://api.deepseek.com'
                assert conv['model'] == 'deepseek-flash'
        finally:
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
                         cfg._api_key, cfg.vision_enabled, cfg.provider) = saved
                db.session.commit()


def test_teacher_edit_config_page_has_domestic_presets(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__dom_vis_t_{suffix}'
    with app.app_context():
        teacher = Teacher(username=username, display_name='视觉教师')
        teacher.set_password('pass123456')
        db.session.add(teacher)
        db.session.commit()
        teacher_id = teacher.id
    try:
        client = _client(app, is_teacher=True, teacher_id=teacher_id,
                         teacher_name='视觉教师', teacher_mode='edit')
        html = client.get('/teacher/ai_config').get_data(as_text=True)
        assert 'visionPresetSelect' in html
        for preset in VISION_MODEL_PRESETS:
            assert preset['model'] in html
    finally:
        with app.app_context():
            Teacher.query.filter_by(id=teacher_id).delete(synchronize_session=False)
            db.session.commit()
