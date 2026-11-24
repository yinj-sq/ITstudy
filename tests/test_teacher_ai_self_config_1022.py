# -*- coding: utf-8 -*-
"""教师编辑模式自定义 AI API、只读模式跟随管理员回归（2026-10-22）。"""
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.ai import _resolve_effective_config
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import (AIConfig, SystemConfig, Teacher,
                        TeacherAIConfig, TeacherAIShare)
from app.utils import password_fingerprint

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


def _save_ai_config():
    cfg = AIConfig.query.first()
    if cfg is None:
        return {'created': True}
    return {
        'created': False, 'enabled': cfg.enabled, 'config_mode': cfg.config_mode,
        'api_url': cfg.api_url, 'model': cfg.model, 'raw_key': cfg._api_key,
        'teacher_enabled': cfg.teacher_enabled,
        'teacher_page_context_default': cfg.teacher_page_context_default,
    }


def _restore_ai_config(saved):
    cfg = AIConfig.query.first()
    if cfg is None:
        return
    if saved.get('created'):
        db.session.delete(cfg)
        return
    cfg.enabled = saved['enabled']
    cfg.config_mode = saved['config_mode']
    cfg.api_url = saved['api_url']
    cfg.model = saved['model']
    cfg._api_key = saved['raw_key']
    cfg.teacher_enabled = saved['teacher_enabled']
    cfg.teacher_page_context_default = saved['teacher_page_context_default']


def _make_teacher(name):
    teacher = Teacher(username=name, display_name='自配教师')
    teacher.set_password('pass123456')
    db.session.add(teacher)
    db.session.commit()
    return teacher.id


def _enable_readonly_code():
    old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
    code_hash = generate_password_hash('readonly123', method='pbkdf2:sha256')
    SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
    db.session.commit()
    return old_code, password_fingerprint(code_hash)


def _cleanup_teacher(teacher_id, username):
    TeacherAIConfig.query.filter_by(teacher_id=teacher_id).delete(
        synchronize_session=False)
    TeacherAIShare.query.filter_by(teacher_id=teacher_id).delete(
        synchronize_session=False)
    Teacher.query.filter_by(username=username).delete(synchronize_session=False)


def test_teacher_edit_self_config_and_readonly_follows_admin(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__tac_{suffix}'
    saved = None
    teacher_id = None
    old_code = None
    code_fp = None
    try:
        with app.app_context():
            saved = _save_ai_config()
            cfg = AIConfig.query.first()
            if cfg is None:
                cfg = AIConfig()
                db.session.add(cfg)
            cfg.enabled = True
            cfg.config_mode = 'admin'
            cfg.api_url = 'https://admin.example.com/v1'
            cfg.model = 'admin-model'
            cfg.api_key = 'sk-admin-test'
            cfg.teacher_enabled = True
            cfg.teacher_page_context_default = True
            db.session.commit()
            teacher_id = _make_teacher(username)
            old_code, code_fp = _enable_readonly_code()

        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='自配教师', teacher_mode='edit')
        status = edit.get('/api/ai/status').get_json()
        assert status['enabled'] is True
        assert status['is_teacher_edit'] is True and status['can_self_config'] is True
        assert status['config_mode'] == 'admin' and status['teacher_configured'] is False

        resp = edit.post('/api/ai/teacher_config', json={
            'api_url': 'https://api.deepseek.com/v1',
            'api_key': 'sk-teacher-self', 'model': 'teacher-self',
            'provider': 'openai',
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success'] is True
        with app.app_context():
            tc = TeacherAIConfig.query.filter_by(teacher_id=teacher_id).first()
            assert tc is not None and tc.api_key == 'sk-teacher-self'
            assert tc._api_key != 'sk-teacher-self'

        status = edit.get('/api/ai/status').get_json()
        assert status['config_mode'] == 'teacher' and status['teacher_configured'] is True
        with app.test_request_context('/'):
            from flask import session as flask_session
            flask_session['is_teacher'] = True
            flask_session['teacher_id'] = teacher_id
            flask_session['teacher_mode'] = 'edit'
            ok, cfg, code = _resolve_effective_config()
            assert ok is True and code == 200
            assert cfg['config_mode'] == 'teacher'
            assert cfg['api_url'] == 'https://api.deepseek.com/v1'
            assert cfg['needs_dns_pinning'] is True

        # 只读模式忽略教师个人配置，使用管理员 API
        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='自配教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        status = readonly.get('/api/ai/status').get_json()
        assert status['enabled'] is True
        assert status['config_mode'] == 'admin' and status['teacher_configured'] is False
        assert status['can_self_config'] is False
        # 只读模式可选择使用本人配置（V6.1.0 新行为）
        resp = readonly.post('/api/ai/teacher_config', json={
            'readonly_use_own': True,
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success'] is True
        status = readonly.get('/api/ai/status').get_json()
        assert status['config_mode'] == 'teacher_readonly'
        assert status['teacher_configured'] is True
        with app.test_request_context('/'):
            from flask import session as flask_session
            flask_session['is_teacher'] = True
            flask_session['teacher_id'] = teacher_id
            flask_session['teacher_mode'] = 'readonly'
            ok, cfg, _ = _resolve_effective_config()
            assert ok is True and cfg['config_mode'] == 'teacher_readonly'
            assert cfg['api_url'] == 'https://api.deepseek.com/v1'
        # 切回管理员配置
        readonly.post('/api/ai/teacher_config', json={
            'readonly_use_own': False,
        }, headers={'X-CSRFToken': CSRF})
        with app.test_request_context('/'):
            from flask import session as flask_session
            flask_session['is_teacher'] = True
            flask_session['teacher_id'] = teacher_id
            flask_session['teacher_mode'] = 'readonly'
            ok, cfg, _ = _resolve_effective_config()
            assert ok is True and cfg['config_mode'] == 'admin'
            assert cfg['api_url'] == 'https://admin.example.com/v1'

        # 清除个人配置后回退管理员
        resp = edit.post('/api/ai/teacher_config', json={'clear': True},
                         headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200
        with app.app_context():
            assert TeacherAIConfig.query.filter_by(teacher_id=teacher_id).first() is None
        status = edit.get('/api/ai/status').get_json()
        assert status['config_mode'] == 'admin' and status['teacher_configured'] is False

        # 删除教师时个人 AI 配置一并清理，不能因 FK 阻断删除
        edit.post('/api/ai/teacher_config', json={
            'api_url': 'https://api.deepseek.com/v1', 'api_key': 'sk-del',
            'model': 'del-model'}, headers={'X-CSRFToken': CSRF})
        admin = _client(app, is_admin=True, admin_name='管理员')
        resp = admin.post('/admin/teacher_account', data={
            'action': 'delete', 'teacher_id': str(teacher_id), 'csrf_token': CSRF,
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert Teacher.query.filter_by(id=teacher_id).first() is None
            assert TeacherAIConfig.query.filter_by(teacher_id=teacher_id).first() is None
        teacher_id = None
    finally:
        with app.app_context():
            if teacher_id:
                _cleanup_teacher(teacher_id, username)
            if saved:
                _restore_ai_config(saved)
            if old_code is not None:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()


def test_teacher_edit_shows_ai_icon_without_any_api_but_readonly_waits(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__tac_noapi_{suffix}'
    saved = None
    teacher_id = None
    old_code = None
    code_fp = None
    try:
        with app.app_context():
            saved = _save_ai_config()
            cfg = AIConfig.query.first()
            if cfg is None:
                cfg = AIConfig()
                db.session.add(cfg)
            cfg.enabled = True
            cfg.api_url = ''
            cfg.model = ''
            cfg._api_key = ''
            cfg.teacher_enabled = True
            db.session.commit()
            teacher_id = _make_teacher(username)
            old_code, code_fp = _enable_readonly_code()

        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='自配教师', teacher_mode='edit')
        status = edit.get('/api/ai/status').get_json()
        assert status['enabled'] is True
        assert status['config_mode'] == 'teacher'
        assert status['teacher_configured'] is False
        assert status['can_self_config'] is True

        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='自配教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        status = readonly.get('/api/ai/status').get_json()
        assert status['enabled'] is False
        assert status['config_mode'] == 'admin'
    finally:
        with app.app_context():
            if teacher_id:
                _cleanup_teacher(teacher_id, username)
            if saved:
                _restore_ai_config(saved)
            if old_code is not None:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()
