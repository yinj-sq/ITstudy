# -*- coding: utf-8 -*-
"""教师 AI 开关、默认只读登录、学科分类与教师账号页布局回归（2026-10-22）。"""
import re
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.ai import _get_actor
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import (AIConfig, Subject, Teacher, SystemConfig,
                        teacher_subject, teacher_class)
from app.utils import password_fingerprint


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = 't'
    return client


def _save_ai_config():
    cfg = AIConfig.query.first()
    if cfg is None:
        return {'created': True}
    return {
        'created': False,
        'enabled': cfg.enabled, 'config_mode': cfg.config_mode,
        'api_url': cfg.api_url, 'model': cfg.model, 'raw_key': cfg._api_key,
        'page_context_default': cfg.page_context_default,
        'teacher_enabled': cfg.teacher_enabled,
        'teacher_page_context_default': cfg.teacher_page_context_default,
    }


def _configure_ai():
    cfg = AIConfig.query.first()
    if cfg is None:
        cfg = AIConfig()
        db.session.add(cfg)
    cfg.enabled = True
    cfg.config_mode = 'admin'
    cfg.api_url = 'https://api.example.com/v1'
    cfg.model = 'teacher-model'
    cfg.api_key = 'sk-teacher-test'
    cfg.page_context_default = True
    cfg.teacher_enabled = True
    cfg.teacher_page_context_default = True
    db.session.commit()
    return cfg


def test_teacher_login_defaults_to_readonly_and_ai_available_in_both_modes(app):
    suffix = uuid.uuid4().hex[:8]
    old_code = None
    saved = None
    teacher_id = None
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            saved = _save_ai_config()
            _configure_ai()
            teacher = Teacher(username=f'__tai_{suffix}', display_name='AI教师')
            teacher.set_password('pass123456')
            db.session.add(teacher)
            db.session.commit()
            teacher_id = teacher.id
            code_hash = generate_password_hash('readonly123', method='pbkdf2:sha256')
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
            db.session.commit()
            code_fp = password_fingerprint(code_hash)

        login_html = app.test_client().get('/teacher/login').get_data(as_text=True)
        tag = re.search(r'<input[^>]*id="readonlyMode"[^>]*>', login_html).group(0)
        assert 'checked' in tag and 'disabled' not in tag, tag

        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='AI教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        status = readonly.get('/api/ai/status').get_json()
        assert status['enabled'] is True and status['is_teacher'] is True
        assert status['config_mode'] == 'admin'

        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='AI教师', teacher_mode='edit')
        assert edit.get('/api/ai/status').get_json()['enabled'] is True

        # 教师端独立开关与默认页面上下文
        with app.app_context():
            cfg = AIConfig.query.first()
            cfg.teacher_enabled = False
            db.session.commit()
        assert readonly.get('/api/ai/status').get_json()['enabled'] is False
        with app.app_context():
            cfg = AIConfig.query.first()
            cfg.teacher_enabled = True
            cfg.teacher_page_context_default = False
            db.session.commit()
        status = edit.get('/api/ai/status').get_json()
        assert status['enabled'] is True and status['page_context_default'] is False

        # 教师 AI 会话归属独立于 guest，只读/编辑两种模式共享同一教师历史
        with app.test_request_context('/'):
            from flask import session as flask_session
            flask_session['is_teacher'] = True
            flask_session['teacher_id'] = teacher_id
            assert _get_actor() == f'teacher:{teacher_id}'
    finally:
        with app.app_context():
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id == teacher_id))
            Teacher.query.filter_by(username=f'__tai_{suffix}').delete(
                synchronize_session=False)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            cfg = AIConfig.query.first()
            if cfg is not None and saved and not saved.get('created'):
                cfg.enabled = saved['enabled']
                cfg.config_mode = saved['config_mode']
                cfg.api_url = saved['api_url']
                cfg.model = saved['model']
                cfg._api_key = saved['raw_key']
                cfg.page_context_default = saved['page_context_default']
                cfg.teacher_enabled = saved['teacher_enabled']
                cfg.teacher_page_context_default = saved['teacher_page_context_default']
            elif cfg is not None and saved and saved.get('created'):
                db.session.delete(cfg)
            db.session.commit()


def test_teacher_subject_categories_only_show_own_subjects(app):
    suffix = uuid.uuid4().hex[:8]
    a_name = f'__tai_subA_{suffix}'
    b_name = f'__tai_subB_{suffix}'
    teacher_id = None
    try:
        with app.app_context():
            sub_a = Subject(name=a_name, sort_order=901)
            sub_b = Subject(name=b_name, sort_order=902)
            teacher = Teacher(username=f'__tai_sub_{suffix}', display_name='学科教师')
            teacher.set_password('pass123456')
            teacher.subjects = [sub_a]
            db.session.add_all([sub_a, sub_b, teacher])
            db.session.commit()
            teacher_id = teacher.id

        teacher_client = _client(app, is_teacher=True, teacher_id=teacher_id,
                                 teacher_name='学科教师', teacher_mode='edit')
        html = teacher_client.get('/study?mode=classroom').get_data(as_text=True)
        assert a_name in html
        assert b_name not in html

        upload_html = teacher_client.get(
            '/teacher/resource-library/upload').get_data(as_text=True)
        assert a_name in upload_html and b_name not in upload_html
    finally:
        with app.app_context():
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id == teacher_id))
            Teacher.query.filter_by(username=f'__tai_sub_{suffix}').delete(
                synchronize_session=False)
            Subject.query.filter(Subject.name.in_([a_name, b_name])).delete(
                synchronize_session=False)
            db.session.commit()


def test_teacher_account_page_uses_dropdowns_and_modals(app):
    suffix = uuid.uuid4().hex[:8]
    subj_name = f'__tai_ui_sub_{suffix}'
    class_name = f'__tai_ui_class_{suffix}'
    class2_name = f'__tai_ui_class2_{suffix}'
    teacher_name = f'__tai_ui_teacher_{suffix}'
    teacher_id = None
    with app.app_context():
        subj = Subject(name=subj_name, sort_order=903)
        from app.models import Class
        cls = Class(name=class_name)
        cls2 = Class(name=class2_name)
        teacher = Teacher(username=teacher_name, display_name='UI教师', grade='高一')
        teacher.set_password('pass123456')
        teacher.subjects = [subj]
        teacher.classes = [cls, cls2]
        db.session.add_all([subj, cls, cls2, teacher])
        db.session.commit()
        teacher_id = teacher.id
        subj_id, class_id, cls2_id = subj.id, cls.id, cls2.id

    admin = _client(app, is_admin=True, admin_name='管理员')
    html = admin.get('/admin/teacher_account').get_data(as_text=True)
    assert 'data-cb-dropdown' in html
    assert 'id="assignModal"' in html and 'id="passwordModal"' in html
    assert 'data-field="assign-grade"' in html
    assert 'name="subject_ids"' in html and 'name="class_ids"' in html
    assert subj_name in html and class_name in html
    cell = re.search(
        r'<td class="small">\s*<div>高一</div>\s*<div class="text-muted">(.*?)</div>\s*</td>',
        html, re.S)
    assert cell is not None
    assert class_name in cell.group(1) and class2_name in cell.group(1)
    assert '、' in cell.group(1)
    assert f'data-subject-ids="{subj_id}"' in html
    class_ids_attr = re.search(r'data-class-ids="([^"]*)"', html).group(1)
    assert {int(x) for x in class_ids_attr.split(',') if x} == {class_id, cls2_id}
    assert f'data-teacher-id="{teacher_id}"' in html

    ai_html = admin.get('/admin/ai_config').get_data(as_text=True)
    assert 'id="teacherEnabledSwitch"' in ai_html
    assert 'id="teacherPageContextSwitch"' in ai_html

    saved = None
    with app.app_context():
        saved = _save_ai_config()
        _configure_ai()
    try:
        resp = admin.post('/admin/ai_config/save', json={
            'teacher_enabled': False,
            'teacher_page_context_default': False,
        }, headers={'X-CSRFToken': 't'})
        assert resp.status_code == 200 and resp.get_json()['success'] is True
        with app.app_context():
            cfg = AIConfig.query.first()
            assert cfg.teacher_enabled is False
            assert cfg.teacher_page_context_default is False
    finally:
        with app.app_context():
            cfg = AIConfig.query.first()
            if cfg is not None and saved and not saved.get('created'):
                cfg.enabled = saved['enabled']
                cfg.config_mode = saved['config_mode']
                cfg.api_url = saved['api_url']
                cfg.model = saved['model']
                cfg._api_key = saved['raw_key']
                cfg.page_context_default = saved['page_context_default']
                cfg.teacher_enabled = saved['teacher_enabled']
                cfg.teacher_page_context_default = saved['teacher_page_context_default']
            elif cfg is not None and saved and saved.get('created'):
                db.session.delete(cfg)
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id == teacher_id))
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == teacher_id))
            Teacher.query.filter_by(username=teacher_name).delete(
                synchronize_session=False)
            Subject.query.filter_by(name=subj_name).delete(synchronize_session=False)
            from app.models import Class
            Class.query.filter(Class.name.in_([class_name, class2_name])).delete(
                synchronize_session=False)
            db.session.commit()
