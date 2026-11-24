# -*- coding: utf-8 -*-
"""仿真实验中心与教师教学台（V6.1.0）。"""
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import Class, SystemConfig, Teacher
from app.utils import password_fingerprint

CSRF = 'hub-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_sim_lab_hub_requires_login_and_shows_both(app):
    anon = app.test_client()
    assert anon.get('/sim-lab').status_code in (302, 303)
    student = _client(app, is_admin=True, admin_name='管理员')
    page = student.get('/sim-lab')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert '仿真实验中心' in text
    assert '化学仿真' in text and '硬件仿真' in text
    assert '打开化学仿真' in text
    hardware = student.get('/sim-lab?tab=hardware')
    assert hardware.status_code == 200
    assert '打开硬件仿真' in hardware.get_data(as_text=True)


def test_menus_merge_simulations():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    base = (root / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'href="/sim-lab"' in base
    assert 'href="/hardware-sim"' not in base
    assert 'href="/chem-lab"' not in base
    classroom = (root / 'templates' / 'admin_classroom.html').read_text(
        encoding='utf-8')
    assert 'href="/sim-lab"' in classroom
    assert 'href="/hardware-sim"' not in classroom
    assert 'href="/chem-lab"' not in classroom
    spa = (root / 'frontend' / 'components' / 'AppHeader.js').read_text(
        encoding='utf-8')
    assert '/sim-lab' in spa
    assert '/hardware-sim' not in spa and '/chem-lab' not in spa


def test_teacher_dashboard_edit_and_readonly(app):
    suffix = uuid.uuid4().hex[:8]
    username = f'__hub_{suffix}'
    teacher_id = None
    old_code = ''
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            teacher = Teacher(username=username, display_name='教学台教师')
            teacher.set_password('pass123456')
            db.session.add(teacher)
            db.session.flush()
            cls = Class(name=f'__hub_cls_{suffix}')
            db.session.add(cls)
            db.session.commit()
            teacher.classes.append(cls)
            db.session.commit()
            teacher_id = teacher.id
            code_hash = generate_password_hash('readonly123',
                                               method='pbkdf2:sha256')
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
            db.session.commit()
            code_fp = password_fingerprint(code_hash)
        edit = _client(app, is_teacher=True, teacher_id=teacher_id,
                       teacher_name='教学台教师', teacher_mode='edit')
        page = edit.get('/teacher/dashboard')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '教学台' in text and '今日课程' in text
        assert '进入课堂' in text and '仿真实验' in text
        assert '资源管理' in text and '批改中心' in text
        assert '我的班级' in text and f'__hub_cls_{suffix}' in text

        readonly = _client(app, is_teacher=True, teacher_id=teacher_id,
                           teacher_name='教学台教师', teacher_mode='readonly',
                           readonly_code_fp=code_fp)
        page = readonly.get('/teacher/dashboard')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '只读课堂模式' in text
        assert '进入课堂' in text and '仿真实验' in text
        # 只读模式不显示编辑/管理快捷入口
        assert '资源管理' not in text
        assert '批改中心' not in text
        assert readonly.get('/sim-lab').status_code == 200
    finally:
        with app.app_context():
            if teacher_id:
                from app.models import teacher_class
                teacher = db.session.get(Teacher, teacher_id)
                if teacher is not None:
                    teacher.classes.clear()
                    db.session.flush()
                db.session.execute(teacher_class.delete().where(
                    teacher_class.c.teacher_id == teacher_id))
                Teacher.query.filter_by(id=teacher_id).delete(
                    synchronize_session=False)
            for cls in Class.query.filter(
                    Class.name.like(f'__hub_cls_{suffix}')).all():
                db.session.delete(cls)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()


def test_offline_ketcher_workbench(app):
    anon = app.test_client()
    assert anon.get('/chem-lab/sketch').status_code in (302, 303)
    admin = _client(app, is_admin=True, admin_name='管理员')
    resp = admin.get('/chem-lab/sketch')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'ketcher/assets/' in text
    csp = resp.headers.get('Content-Security-Policy', '')
    assert "'wasm-unsafe-eval'" in csp
    policy = resp.headers.get('Permissions-Policy', '')
    assert 'fullscreen=(self)' in policy and 'moldraw' not in policy
    assert admin.get('/mol-draw').status_code == 404
    hub = admin.get('/sim-lab').get_data(as_text=True)
    assert 'Ketcher' in hub and 'mol-draw' not in hub
