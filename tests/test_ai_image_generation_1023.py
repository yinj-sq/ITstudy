# -*- coding: utf-8 -*-
"""生图模型一期回归：配置、直接生图、提示词优化、权限与图片鉴权（2026-10-23）。"""
import os
import uuid

import pytest

from app import create_app
from app.blueprints import ai as ai_mod
from app.extensions import db
from app.models import (AIChatMessage, AIImage, AIImageConfig,
                        Class, Student, SystemConfig)
from app.blueprints.ai import STUDENT_PAGE_ONLY_KEY

CSRF = 't'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _image_cfg_snapshot():
    cfg = AIImageConfig.query.first()
    if cfg is None:
        return {'created': True}
    fields = ('enabled', 'provider', 'api_url', 'model', 'size', 'quality',
              'max_images', 'timeout_seconds', 'allow_student',
              'allow_teacher', 'auto_intent', '_api_key')
    return {'created': False, **{f: getattr(cfg, f) for f in fields}}


def _restore_image_cfg(saved):
    cfg = AIImageConfig.query.first()
    if cfg is None:
        return
    if saved.get('created'):
        db.session.delete(cfg)
        return
    for k, v in saved.items():
        if k != 'created':
            setattr(cfg, k, v)


def _configure_image(enabled=True, allow_student=True, allow_teacher=True):
    cfg = AIImageConfig.query.first()
    if cfg is None:
        cfg = AIImageConfig()
        db.session.add(cfg)
    cfg.enabled = enabled
    cfg.provider = 'openai_images'
    cfg.api_url = 'https://image.example.com/v1'
    cfg.model = 'gpt-image-1'
    cfg.size = '1024x1024'
    cfg.quality = ''
    cfg.max_images = 1
    cfg.timeout_seconds = 30
    cfg.allow_student = allow_student
    cfg.allow_teacher = allow_teacher
    cfg.api_key = 'sk-image-test'
    db.session.commit()
    return cfg


def _make_student(name):
    cls = Class(name=f'__img_cls_{name}')
    stu = Student(name='生图学生', student_number=name, class_id=None,
                  student_class=cls.name, has_changed_password=True)
    stu.set_password('pass123456')
    db.session.add_all([cls, stu])
    db.session.commit()
    return cls.id, stu.id


def _cleanup_student(cls_id, stu_id):
    AIChatMessage.query.filter_by(student_id=stu_id).delete(
        synchronize_session=False)
    Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
    Class.query.filter_by(id=cls_id).delete(synchronize_session=False)


def test_image_generation_think_and_ownership(app, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    saved = None
    cls1 = stu1 = cls2 = stu2 = None
    image_ids = []
    try:
        with app.app_context():
            saved = _image_cfg_snapshot()
            _configure_image()
            cls1, stu1 = _make_student(f'__img_a_{suffix}')
            cls2, stu2 = _make_student(f'__img_b_{suffix}')
        captured = {}

        def fake_generate(prompt, cfg):
            captured['prompt'] = prompt
            return True, [(PNG, 'image/png')]

        monkeypatch.setattr(ai_mod, '_image_api_generate', fake_generate)
        monkeypatch.setattr(ai_mod, '_optimize_image_prompt',
                            lambda p: ('优化后的提示词：' + p, '已优化生图提示词'))

        c1 = _client(app, student_id=stu1, student_name='生图学生',
                     has_changed_password=True)
        resp = c1.post('/api/ai/image', json={
            'message': '画一只在黑板前讲课的机器人',
            'optimize': True,
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data['success'] is True and len(data['images']) == 1
        assert captured['prompt'] == '优化后的提示词：画一只在黑板前讲课的机器人'
        assert data['prompt_used'] == captured['prompt']

        with app.app_context():
            rec = AIImage.query.filter_by(actor=f'student:{stu1}').first()
            assert rec is not None
            image_ids.append(rec.id)
            abs_path = os.path.join(os.path.dirname(app.static_folder),
                                    rec.file_path)
            assert os.path.isfile(abs_path)
            msgs = AIChatMessage.query.filter_by(
                student_id=stu1, session_id=data['session_id']).order_by(
                AIChatMessage.id).all()
            assert [m.role for m in msgs] == ['user', 'assistant']
            assert '![生成图片](' in msgs[-1].content

        image_url = data['images'][0]
        assert c1.get(image_url).status_code == 200
        c2 = _client(app, student_id=stu2, student_name='其他学生',
                     has_changed_password=True)
        assert c2.get(image_url).status_code == 403
    finally:
        with app.app_context():
            for iid in image_ids:
                rec = db.session.get(AIImage, iid)
                if rec:
                    p = os.path.join(os.path.dirname(app.static_folder),
                                     rec.file_path)
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                    db.session.delete(rec)
            if stu1:
                _cleanup_student(cls1, stu1)
            if stu2:
                _cleanup_student(cls2, stu2)
            if saved:
                _restore_image_cfg(saved)
            db.session.commit()


def test_image_role_and_page_only_restrictions(app):
    suffix = uuid.uuid4().hex[:8]
    saved = None
    cls_id = stu_id = None
    old_page_only = None
    try:
        with app.app_context():
            saved = _image_cfg_snapshot()
            _configure_image(allow_student=False)
            cls_id, stu_id = _make_student(f'__img_perm_{suffix}')
            old_page_only = SystemConfig.get(STUDENT_PAGE_ONLY_KEY, '0')
        c = _client(app, student_id=stu_id, student_name='生图学生',
                    has_changed_password=True)
        status = c.get('/api/ai/status').get_json()
        assert status['image_enabled'] is False
        assert c.post('/api/ai/image', json={'message': '画一只猫'},
                      headers={'X-CSRFToken': CSRF}).status_code == 403

        with app.app_context():
            cfg = AIImageConfig.query.first()
            cfg.allow_student = True
            SystemConfig.set(STUDENT_PAGE_ONLY_KEY, '1')
            db.session.commit()
        status = c.get('/api/ai/status').get_json()
        assert status['image_enabled'] is False
        assert c.post('/api/ai/image', json={'message': '画一只猫'},
                      headers={'X-CSRFToken': CSRF}).status_code == 403
    finally:
        with app.app_context():
            if stu_id:
                _cleanup_student(cls_id, stu_id)
            SystemConfig.set(STUDENT_PAGE_ONLY_KEY, old_page_only or '0')
            if saved:
                _restore_image_cfg(saved)
            db.session.commit()


def test_admin_image_config_ui_and_save(app):
    saved = None
    try:
        with app.app_context():
            saved = _image_cfg_snapshot()
        admin = _client(app, is_admin=True, admin_name='管理员')
        html = admin.get('/admin/ai_config').get_data(as_text=True)
        for marker in ('imageEnabledSwitch', 'imageApiUrl', 'imageModel',
                       'imageAllowStudent', 'imageAllowTeacher'):
            assert marker in html
        resp = admin.post('/admin/ai_config/save', json={
            'image_enabled': True,
            'image_provider': 'openai_images',
            'image_api_url': 'https://image.example.com/v1',
            'image_api_key': 'sk-image-admin',
            'image_model': 'gpt-image-1',
            'image_size': '1024x1024',
            'image_quality': '',
            'image_max_images': 1,
            'image_timeout_seconds': 60,
            'image_allow_student': True,
            'image_allow_teacher': True,
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success'] is True
        with app.app_context():
            cfg = AIImageConfig.query.first()
            assert cfg.enabled is True and cfg.model == 'gpt-image-1'
            assert cfg.api_key == 'sk-image-admin'
            assert cfg._api_key != 'sk-image-admin'
    finally:
        with app.app_context():
            if saved:
                _restore_image_cfg(saved)
            db.session.commit()
