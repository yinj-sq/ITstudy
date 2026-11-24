# -*- coding: utf-8 -*-
"""AI 面板角色与课堂预览嵌入回归（2026-10-23）。

1. 管理员端 AI 状态必须是管理员配置模式，不能因 AIConfig.config_mode='student'
   被渲染成学生自行配置引导。
2. 课堂电子文档 iframe 使用 embed=1，不再继承 base.html 的导航/AI 面板，
   避免父课堂页与预览页各出现一个 AI 助手。
"""
import os
import shutil
import uuid

from app import create_app
from app.extensions import db
from app.models import AIConfig

CSRF = 't'


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_admin_ai_mode_and_embedded_preview_have_single_widget():
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__ai_embed_{sfx}'
    upload_dir = os.path.join('static', 'uploads', dir_name)
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, 'lesson.pdf'), 'wb') as f:
        f.write(b'%PDF-1.4\n%%EOF')
    app = create_app()
    saved = None
    created = False
    try:
        with app.app_context():
            cfg = AIConfig.query.first()
            created = cfg is None
            if created:
                cfg = AIConfig()
                db.session.add(cfg)
            saved = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                     cfg._api_key)
            cfg.enabled = True
            cfg.config_mode = 'student'
            cfg.api_url, cfg.model = 'https://api.example.com/v1', 'ai-widget-test'
            cfg.api_key = 'sk-widget-test'
            db.session.commit()

        admin = _client(app, is_admin=True, admin_name='管理员')
        status = admin.get('/api/ai/status').get_json()
        assert status['is_admin'] is True
        assert status['config_mode'] == 'admin'
        assert status['student_configured'] is False

        file_url = f'/static/uploads/{dir_name}/lesson.pdf'
        embedded = admin.get(
            '/study/preview', query_string={
                'file': file_url, 'name': 'lesson', 'embed': '1'})
        assert embedded.status_code == 200
        embedded_html = embedded.get_data(as_text=True)
        assert 'ai-chat.js' not in embedded_html
        assert 'id="aiFab"' not in embedded_html
        assert '<nav class="navbar' not in embedded_html

        standalone = admin.get(
            '/study/preview', query_string={'file': file_url, 'name': 'lesson'})
        assert standalone.status_code == 200
        assert 'ai-chat.js' in standalone.get_data(as_text=True)
    finally:
        with app.app_context():
            cfg = AIConfig.query.first()
            if cfg is not None:
                if created:
                    db.session.delete(cfg)
                else:
                    (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                     cfg._api_key) = saved
                db.session.commit()
        shutil.rmtree(upload_dir, ignore_errors=True)
