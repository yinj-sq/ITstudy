# -*- coding: utf-8 -*-
"""硬件仿真整合回归（2026-11-02）。

覆盖：
- 掌控板 / ESP32-S3 静态应用迁入与完整版产物
- 掌控板发布版不含讯飞凭据
- /hardware-sim 登录鉴权与账号 uid 命名空间
- 三端菜单接入与安全头按路径放宽
- ESP32-S3 默认简体中文
"""
import pathlib
import re
import uuid

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import Student, Teacher

ROOT = pathlib.Path(__file__).resolve().parent.parent
MM = ROOT / 'static' / 'hardware-sim' / 'mmake'
ESP = ROOT / 'static' / 'hardware-sim' / 'esp32-s3'


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture()
def student_id(app):
    with app.app_context():
        stu = Student(name='__hw_sim_student__',
                      student_number=f'__hw_{uuid.uuid4().hex[:10]}',
                      password_hash='x', is_activated=True,
                      has_changed_password=True)
        db.session.add(stu)
        db.session.commit()
        sid = stu.id
    yield sid
    with app.app_context():
        Student.query.filter_by(id=sid).delete(synchronize_session=False)
        db.session.commit()
    cache.delete(f'session:check:{sid}')


@pytest.fixture()
def teacher_id(app):
    with app.app_context():
        teacher = Teacher(username=f'__hw_t_{uuid.uuid4().hex[:10]}',
                          display_name='__hw_teacher__')
        teacher.set_password('pass123456')
        db.session.add(teacher)
        db.session.commit()
        tid = teacher.id
    yield tid
    with app.app_context():
        Teacher.query.filter_by(id=tid).delete(synchronize_session=False)
        db.session.commit()
    cache.delete(f'session:teacher:{tid}')


def test_static_apps_present():
    assert (MM / 'index.html').is_file()
    for name in ('blockly_compressed.js', 'blocks_compressed.js',
                 'javascript_compressed.js', 'python_compressed.js',
                 'msg/zh-hans.js'):
        assert (MM / 'vendor' / 'blockly' / name).is_file()
    assert (MM / 'js' / 'store.js').is_file()
    assert (ESP / 'index.html').is_file()
    assert list((ESP / 'assets').glob('*.js'))
    assert (ESP / 'firmware' / 'index.json').is_file()
    assert (ESP / 'reference' / 'index.json').is_file()
    assert not list(ESP.rglob('*.map'))


def test_mmake_credentials_removed():
    src = (MM / 'js' / 'xfyun.js').read_text(encoding='utf-8-sig')
    m = re.search(r'var DEFAULT_CREDS = \{[\s\S]*?\n  \};', src)
    assert m, 'DEFAULT_CREDS 块未找到'
    assert all(v == '' for v in re.findall(r"'([^']*)'", m.group(0)))
    assert not re.search(r"(?:apiKey|apiSecret|appId)\s*:\s*'[^']+'", src)


def test_mmake_uid_storage_patch():
    src = (MM / 'js' / 'store.js').read_text(encoding='utf-8-sig')
    assert 'URLSearchParams' in src and "get('uid')" in src
    assert "'u_' + UID + '__'" in src
    assert "zkb_store' + (UID" in src


def test_esp32_default_chinese_and_uid_patch():
    html = (ESP / 'index.html').read_text(encoding='utf-8')
    assert 'lang="zh-CN"' in html
    assert 'ESP32-S3 仿真' in html
    assert 'src="/assets/' not in html and 'href="/assets/' not in html
    js = ''.join(p.read_text(encoding='utf-8', errors='ignore')
                 for p in (ESP / 'assets').glob('*.js'))
    assert 'URLSearchParams' in js and 'uid' in js and 'u_' in js


def test_licenses_present():
    assert (MM / 'LICENSE').is_file()
    assert (MM / 'vendor' / 'blockly' / 'LICENSE-APACHE-2.0.txt').is_file()
    assert (ESP / 'LICENSE').is_file()
    assert (ESP / 'fonts' / 'OFL.txt').is_file()
    assert (ESP / 'fonts' / 'FONT-NOTICES.txt').is_file()
    assert (ROOT / 'static' / 'hardware-sim' / 'THIRD_PARTY_NOTICES.txt').is_file()
    assert (ROOT / 'static' / 'hardware-sim' / 'BUILD_INFO.txt').is_file()


def test_artifact_verification_script_passes():
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, 'tools/verify_hardware_sim_artifacts.py'],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert proc.returncode == 0, (proc.stdout or '') + (proc.stderr or '')


def test_route_requires_login_and_passes_uid(app, student_id, teacher_id, monkeypatch):
    monkeypatch.setattr('app.blueprints.auth._get_active_class_ids', lambda: set())
    client = app.test_client()

    assert client.get('/hardware-sim').status_code == 302

    with client.session_transaction() as sess:
        sess.clear()
        sess['student_id'] = student_id
        sess['student_name'] = '__hw_sim_student__'
        sess['csrf_token'] = 't'
    resp = client.get('/hardware-sim')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f'uid=student_{student_id}' in html
    assert 'hwFrameMmake' in html and 'hwFrameEsp32' in html
    assert 'data-src=' in html and 'allowfullscreen' in html

    with client.session_transaction() as sess:
        sess.clear()
        sess['is_teacher'] = True
        sess['teacher_id'] = teacher_id
        sess['teacher_name'] = '__hw_teacher__'
        sess['teacher_mode'] = 'edit'
        sess['csrf_token'] = 't'
    resp = client.get('/hardware-sim')
    assert resp.status_code == 200
    assert f'uid=teacher_{teacher_id}' in resp.get_data(as_text=True)

    with client.session_transaction() as sess:
        sess.clear()
        sess['is_admin'] = True
        sess['admin_name'] = '__hw_admin__'
        sess['csrf_token'] = 't'
    resp = client.get('/hardware-sim')
    assert resp.status_code == 200
    assert 'uid=admin' in resp.get_data(as_text=True)


def test_menus_wired():
    base = _read('templates/base.html')
    classroom = _read('templates/admin_classroom.html')
    header = _read('frontend/components/AppHeader.js')
    page = _read('templates/hardware_sim.html')

    assert base.count('href="/sim-lab"') >= 3
    assert classroom.count('href="/sim-lab"') >= 1
    assert header.count('href="/sim-lab"') >= 4
    assert 'href="/hardware-sim"' not in base
    assert 'href="/hardware-sim"' not in classroom
    assert 'href="/hardware-sim"' not in header
    assert '/admin/hardware-sim' not in base + classroom + header
    assert 'hwFrameMmake' in page and 'hwFrameEsp32' in page
    assert '图形编程仿真' in page and 'ESP32-S3 仿真' in page
    assert 'versioned_static' in page and 'uid=' in page


def test_esp32_hashed_assets_are_immutable(app):
    asset = next((ESP / 'assets').glob('*.js')).name
    client = app.test_client()
    resp = client.get(f'/static/hardware-sim/esp32-s3/assets/{asset}')
    assert resp.status_code == 200
    cache = resp.headers.get('Cache-Control', '')
    assert 'immutable' in cache and 'max-age=31536000' in cache
    idx = client.get('/static/hardware-sim/esp32-s3/index.html')
    assert 'no-cache' in idx.headers.get('Cache-Control', '')


def test_readonly_teacher_can_open_hardware_sim(app, teacher_id, monkeypatch):
    from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
    from app.utils import password_fingerprint

    code_hash = 'readonly-test-hash'

    class FakeConfig:
        @classmethod
        def get(cls, key):
            return code_hash if key == TEACHER_READONLY_CODE_KEY else ''

    monkeypatch.setattr('app.blueprints.auth.SystemConfig', FakeConfig)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_teacher'] = True
        sess['teacher_id'] = teacher_id
        sess['teacher_name'] = '__hw_teacher__'
        sess['teacher_mode'] = 'readonly'
        sess['readonly_code_fp'] = password_fingerprint(code_hash)
        sess['csrf_token'] = 't'
    resp = client.get('/hardware-sim')
    assert resp.status_code == 200
    assert f'uid=teacher_{teacher_id}' in resp.get_data(as_text=True)


def test_readonly_teacher_whitelist_includes_hardware_sim():
    src = _read('app/blueprints/auth.py')
    assert "path.startswith('/hardware-sim')" in src


def test_security_headers_are_path_scoped(app, student_id, monkeypatch):
    monkeypatch.setattr('app.blueprints.auth._get_active_class_ids', lambda: set())
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['student_id'] = student_id
        sess['student_name'] = '__hw_sim_student__'
        sess['csrf_token'] = 't'

    host = client.get('/hardware-sim')
    assert host.status_code == 200
    assert 'microphone=(self)' in host.headers['Permissions-Policy']
    assert 'serial=(self)' in host.headers['Permissions-Policy']
    assert "'unsafe-eval'" not in host.headers['Content-Security-Policy']

    mm = client.get('/static/hardware-sim/mmake/index.html')
    assert mm.status_code == 200
    mm_csp = mm.headers['Content-Security-Policy']
    assert "'unsafe-eval'" in mm_csp
    assert 'media-src' in mm_csp
    for host in ('iat-api.xfyun.cn', 'tts-api.xfyun.cn', 'webapi.xfyun.cn',
                 'tupapi.xfyun.cn', 'rest-api.xfyun.cn', 'api.xf-yun.com',
                 'api.open-meteo.com'):
        assert host in mm_csp
    assert '*.xfyun.cn' not in mm_csp and '*.xf-yun.com' not in mm_csp
    assert "connect-src 'self'" not in mm_csp
    assert 'camera=(self)' in mm.headers['Permissions-Policy']

    esp = client.get('/static/hardware-sim/esp32-s3/index.html')
    assert esp.status_code == 200
    esp_csp = esp.headers['Content-Security-Policy']
    assert 'fonts.gstatic.com' not in esp_csp and 'fonts.googleapis.com' not in esp_csp
    # ESP32-S3 字体已自托管；font-src 仅允许同源、data: 与前端依赖回退用的
    # 有限 CDN 白名单，不允许通配符或 Google Fonts。
    font_src = next(part.strip() for part in esp_csp.split(';')
                    if part.strip().startswith('font-src'))
    font_tokens = font_src.split()[1:]
    assert "'self'" in font_tokens and 'data:' in font_tokens
    assert all(token.startswith('https://') for token in font_tokens
               if token not in ("'self'", 'data:'))
    assert not any('*' in token for token in font_tokens)
    assert "'unsafe-eval'" not in esp_csp
    assert '/static/hardware-sim/esp32-s3/' in esp_csp
    assert "connect-src 'self'" not in esp_csp

    study = client.get('/study')
    assert "'unsafe-eval'" not in study.headers['Content-Security-Policy']
    assert 'camera=()' in study.headers['Permissions-Policy']
