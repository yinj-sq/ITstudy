# -*- coding: utf-8 -*-
"""学生端页面回归（2026-10-19 浏览器实测发现）。

1. 结果页综合题只渲染子题、缺少“背景概述”，学生无法回看阅读材料。
2. 首登强制改密页仍加载 AI 面板：/api/ai/status 被强制改密中间件 403，
   控制台报错；同时 /api/heartbeat 在中间件层被误拦（装饰器已放行心跳）。
"""
import pathlib

from app import create_app
from app.extensions import db
from app.models import AttendanceRecord, Class, ClassroomSetting, Student
from app.utils import password_fingerprint
from werkzeug.security import generate_password_hash

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_result_page_renders_comprehensive_background():
    src = (ROOT / 'templates' / 'result.html').read_text(encoding='utf-8')
    assert '{% if question.background %}' in src
    assert 'background|convert_md_images|sanitize_rich_text' in src


def test_homework_submission_attachments_have_preview_and_download():
    result_src = (ROOT / 'templates' / 'student_homework_result.html').read_text(
        encoding='utf-8')
    submit_src = (ROOT / 'templates' / 'student_homework_submit.html').read_text(
        encoding='utf-8')
    for src, owner in ((result_src, 'sub.id'), (submit_src, 'existing.id')):
        assert f'/static/submissions/{{{{ {owner} }}}}' in src
        assert 'homework.student_preview_submission' in src
        assert 'download' in src
        assert '预览' in src
    assert 'existing_files' in submit_src


def test_base_hides_ai_panel_during_forced_password_change():
    src = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert ("session.get('student_id') and not session.get('must_change_password')"
            in src)
    assert 'ai-chat.js' in src


def test_base_lazy_loads_ai_assets_on_first_open():
    """菜单页不再首屏加载 AI 脚本，点击悬浮入口时才加载。"""
    src = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'id="aiFabLazy"' in src
    assert 'loadAsset' in src
    assert "versioned_static('js/ai-chat.js')" in src
    assert '<script src="{{ versioned_static(\'js/ai-chat.js\') }}"' not in src


def test_heartbeat_allowed_during_forced_password_change():
    app = create_app()
    class_name = '学生端回归班'
    number = '学生端回归生'
    with app.app_context():
        old_setting = ClassroomSetting.query.first()
        original = None
        if old_setting:
            original = (old_setting.active_class_id, old_setting.current_schedule_id,
                        old_setting.display_message, old_setting.seat_offset,
                        old_setting.auto_switch)
        cls = Class(name=class_name, description='学生端回归')
        db.session.add(cls)
        db.session.flush()
        stu = Student(name=number, student_number=number, student_class=class_name,
                      class_id=cls.id, password_hash=generate_password_hash(
                          'init-pass', method='pbkdf2:sha256'),
                      has_changed_password=False, is_activated=True)
        db.session.add(stu)
        db.session.flush()
        setting = old_setting or ClassroomSetting()
        setting.active_class_id = cls.id
        db.session.add(setting)
        db.session.commit()
        sid = stu.id
        fingerprint = password_fingerprint(stu.password_hash)

    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['student_id'] = sid
            sess['pwd_fp'] = fingerprint
            sess['csrf_token'] = 't'
            sess['must_change_password'] = True
        resp = client.post('/api/heartbeat', json={},
                           headers={'X-CSRFToken': 't'})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        assert resp.get_json().get('success') is True
    finally:
        with app.app_context():
            setting = ClassroomSetting.query.first()
            if setting:
                if original:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = original
                else:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
                db.session.flush()
            db.session.query(AttendanceRecord).filter_by(student_id=sid).delete(
                synchronize_session=False)
            db.session.query(Student).filter_by(student_number=number).delete(
                synchronize_session=False)
            db.session.query(Class).filter_by(name=class_name).delete(
                synchronize_session=False)
            db.session.commit()
