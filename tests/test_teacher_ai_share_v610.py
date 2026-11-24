# -*- coding: utf-8 -*-
"""教师 AI 配置 V6.1.0：确认保存、只读来源、班级共享。"""
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.ai import (_get_teacher_transient_config,
                               _resolve_effective_config)
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import (AIConfig, Class, Student, SystemConfig, Teacher,
                        TeacherAIConfig, TeacherAIShare)
from app.utils import password_fingerprint

CSRF = 'ai-share-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, data):
    return client.post('/api/ai/teacher_config', json=data,
                       headers={'X-CSRFToken': CSRF})


def _make_teacher(name):
    teacher = Teacher(username=name, display_name='共享教师')
    teacher.set_password('pass123456')
    db.session.add(teacher)
    db.session.commit()
    return teacher


def _admin_config():
    cfg = AIConfig.query.first()
    if cfg is None:
        cfg = AIConfig()
        db.session.add(cfg)
    cfg.enabled = True
    cfg.config_mode = 'admin'
    cfg.api_url = 'https://admin.example.com/v1'
    cfg.model = 'admin-model'
    cfg.api_key = 'sk-admin-share'
    cfg.teacher_enabled = True
    db.session.commit()
    return cfg


def _readonly_fp():
    code_hash = generate_password_hash('readonly123', method='pbkdf2:sha256')
    SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
    db.session.commit()
    return password_fingerprint(code_hash)


def test_persist_and_transient_teacher_config(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__ai_persist_{suffix}'
    teacher_id = None
    try:
        with app.app_context():
            _admin_config()
            teacher = _make_teacher(username)
            teacher_id = teacher.id
        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='共享教师', teacher_mode='edit')
        # 不保存到数据库：仅本次登录生效
        resp = _post(edit, {
            'api_url': 'https://api.deepseek.com/v1',
            'api_key': 'sk-transient', 'model': 'transient-model',
            'provider': 'openai', 'persist': False,
        })
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.app_context():
            assert TeacherAIConfig.query.filter_by(
                teacher_id=teacher_id).first() is None
            transient = _get_teacher_transient_config(teacher_id)
            assert transient and transient['model'] == 'transient-model'
        with app.test_request_context('/'):
            from flask import session as fs
            fs['is_teacher'] = True
            fs['teacher_id'] = teacher_id
            fs['teacher_mode'] = 'edit'
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'teacher_transient'
            assert cfg['model'] == 'transient-model'

        # 保存到数据库：写入并清除临时配置
        resp = _post(edit, {
            'api_url': 'https://api.deepseek.com/v1',
            'api_key': 'sk-persist', 'model': 'persist-model',
            'provider': 'openai', 'persist': True,
        })
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.app_context():
            tc = TeacherAIConfig.query.filter_by(teacher_id=teacher_id).first()
            assert tc is not None and tc.model == 'persist-model'
            assert _get_teacher_transient_config(teacher_id) is None
        with app.test_request_context('/'):
            from flask import session as fs
            fs['is_teacher'] = True
            fs['teacher_id'] = teacher_id
            fs['teacher_mode'] = 'edit'
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'teacher'
            assert cfg['model'] == 'persist-model'
    finally:
        with app.app_context():
            if teacher_id:
                TeacherAIShare.query.filter_by(teacher_id=teacher_id).delete(
                    synchronize_session=False)
                TeacherAIConfig.query.filter_by(teacher_id=teacher_id).delete(
                    synchronize_session=False)
                Teacher.query.filter_by(id=teacher_id).delete(
                    synchronize_session=False)
            db.session.commit()


def test_readonly_can_choose_own_config(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__ai_readonly_{suffix}'
    teacher_id = None
    old_code = ''
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            _admin_config()
            teacher = _make_teacher(username)
            teacher_id = teacher.id
            tc = TeacherAIConfig(teacher_id=teacher_id,
                                 api_url='https://api.deepseek.com/v1',
                                 model='teacher-model')
            tc.api_key = 'sk-teacher-readonly'
            db.session.add(tc)
            db.session.commit()
            code_fp = _readonly_fp()
        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='共享教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        # 默认管理员
        with app.test_request_context('/'):
            from flask import session as fs
            fs['is_teacher'] = True
            fs['teacher_id'] = teacher_id
            fs['teacher_mode'] = 'readonly'
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'admin'
        # 选择本人配置
        resp = _post(readonly, {'readonly_use_own': True})
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.test_request_context('/'):
            from flask import session as fs
            fs['is_teacher'] = True
            fs['teacher_id'] = teacher_id
            fs['teacher_mode'] = 'readonly'
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'teacher_readonly'
            assert cfg['model'] == 'teacher-model'
        status = readonly.get('/api/ai/status').get_json()
        assert status['config_mode'] == 'teacher_readonly'
    finally:
        with app.app_context():
            if teacher_id:
                TeacherAIConfig.query.filter_by(teacher_id=teacher_id).delete(
                    synchronize_session=False)
                Teacher.query.filter_by(id=teacher_id).delete(
                    synchronize_session=False)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()


def test_teacher_ai_config_page_modes(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__ai_page_{suffix}'
    teacher_id = None
    old_code = ''
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            _admin_config()
            teacher = _make_teacher(username)
            teacher_id = teacher.id
            code_fp = _readonly_fp()
        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='共享教师', teacher_mode='edit')
        page = edit.get('/teacher/ai_config')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '个人 API 配置' in text
        assert '共享给任教班级' in text
        assert '只读模式 AI 来源' in text
        assert 'persistConfig' in text

        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='共享教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        page = readonly.get('/teacher/ai_config')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '只读模式 AI 来源' in text
        assert '<i class="fas fa-save me-1"></i>保存个人配置' not in text
        assert '共享给任教班级' not in text
        assert '保存来源选择' in text
    finally:
        with app.app_context():
            if teacher_id:
                TeacherAIConfig.query.filter_by(teacher_id=teacher_id).delete(
                    synchronize_session=False)
                Teacher.query.filter_by(id=teacher_id).delete(
                    synchronize_session=False)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()


def test_teacher_share_config_to_classes(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__ai_share_{suffix}'
    tid = aid = bid = said = sbid = None
    try:
        with app.app_context():
            _admin_config()
            teacher = _make_teacher(username)
            cls_a = Class(name=f'__ai_cls_a_{suffix}')
            cls_b = Class(name=f'__ai_cls_b_{suffix}')
            stu_a = Student(name='共享学生A', student_number=f'__ai_sa_{suffix}',
                            student_class=cls_a.name, has_changed_password=True)
            stu_b = Student(name='共享学生B', student_number=f'__ai_sb_{suffix}',
                            student_class=cls_b.name, has_changed_password=True)
            db.session.add_all([cls_a, cls_b, stu_a, stu_b])
            db.session.flush()
            stu_a.class_id = cls_a.id
            stu_b.class_id = cls_b.id
            teacher.classes.append(cls_a)
            tc = TeacherAIConfig(teacher_id=teacher.id,
                                 api_url='https://api.deepseek.com/v1',
                                 model='share-model')
            tc.api_key = 'sk-share'
            db.session.add(tc)
            db.session.commit()
            tid, aid, bid, said, sbid = (
                teacher.id, cls_a.id, cls_b.id, stu_a.id, stu_b.id)
        edit = _client(app, is_teacher=True, teacher_id=tid,
                       teacher_name='共享教师', teacher_mode='edit')
        # 不能共享给非本人任教班级
        resp = _post(edit, {'share_class_ids': [bid]})
        assert resp.status_code == 400
        resp = _post(edit, {'share_class_ids': [aid]})
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.app_context():
            assert TeacherAIShare.query.filter_by(
                teacher_id=tid, class_id=aid).count() == 1
        # A 班学生命中共享教师；B 班学生回退管理员
        with app.test_request_context('/'):
            from flask import session as fs
            fs['student_id'] = said
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'teacher_shared'
            assert cfg['owner_teacher_name'] == '共享教师'
        with app.test_request_context('/'):
            from flask import session as fs
            fs['student_id'] = sbid
            ok, cfg, _ = _resolve_effective_config()
            assert ok and cfg['config_mode'] == 'admin'
        # 清空共享
        resp = _post(edit, {'share_class_ids': []})
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.app_context():
            assert TeacherAIShare.query.filter_by(
                teacher_id=tid).count() == 0
    finally:
        with app.app_context():
            from app.models import teacher_class
            if tid:
                TeacherAIShare.query.filter_by(teacher_id=tid).delete(
                    synchronize_session=False)
                TeacherAIConfig.query.filter_by(teacher_id=tid).delete(
                    synchronize_session=False)
                db.session.execute(teacher_class.delete().where(
                    teacher_class.c.teacher_id == tid))
                teacher = db.session.get(Teacher, tid)
                if teacher is not None:
                    db.session.delete(teacher)
            for student_id in (said, sbid):
                if student_id:
                    student = db.session.get(Student, student_id)
                    if student is not None:
                        db.session.delete(student)
            for class_id in (aid, bid):
                if class_id:
                    cls = db.session.get(Class, class_id)
                    if cls is not None:
                        db.session.delete(cls)
            db.session.commit()
