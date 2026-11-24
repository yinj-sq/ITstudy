# -*- coding: utf-8 -*-
"""2026-11-11 性能优化回归：逐题分析短缓存、AI 流并发运行时覆盖、大文件下载池。"""
import math
import os

import pytest

from app import create_app
from app.extensions import db
from app.models import SystemConfig
from app.services import download_pool

CSRF = 'perf-settings-1111'
SWITCH_KEYS = ('student_access_enabled', 'admin_remote_enabled',
               'class_buttons_enabled', 'courseware_public_enabled')
AI_LIMIT_KEY = 'ai_max_concurrent_streams'

# 略大于 1MB：测试里把阈值设为 1MB
PAYLOAD = bytes(range(256)) * 4096 + b'end'


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture
def admin_client(app):
    client = app.test_client()
    with client.session_transaction() as values:
        values.clear()
        values.update(is_admin=True, csrf_token=CSRF)
    return client


# ── AI 流式并发运行时覆盖 ─────────────────────────────────────
def _stream_limit(app):
    from app.blueprints import ai
    with app.test_request_context('/api/ai/chat/stream'):
        return ai._global_stream_limit()


def test_ai_stream_limit_uses_runtime_override_and_bounds(app):
    with app.app_context():
        previous = SystemConfig.get(AI_LIMIT_KEY)
    try:
        with app.app_context():
            SystemConfig.set(AI_LIMIT_KEY, '7')
            db.session.commit()
        assert _stream_limit(app) == 7
        # 越界/非法值回退 deploy 默认，不生效
        with app.app_context():
            SystemConfig.set(AI_LIMIT_KEY, '999')
            db.session.commit()
        assert _stream_limit(app) == int(app.config['AI_MAX_CONCURRENT_STREAMS'])
        with app.app_context():
            SystemConfig.set(AI_LIMIT_KEY, 'abc')
            db.session.commit()
        assert _stream_limit(app) == int(app.config['AI_MAX_CONCURRENT_STREAMS'])
        # 空值 = 恢复部署默认
        with app.app_context():
            SystemConfig.set(AI_LIMIT_KEY, '')
            db.session.commit()
        assert _stream_limit(app) == int(app.config['AI_MAX_CONCURRENT_STREAMS'])
    finally:
        with app.app_context():
            SystemConfig.query.filter_by(key=AI_LIMIT_KEY).delete(
                synchronize_session=False)
            if previous is not None:
                SystemConfig.set(AI_LIMIT_KEY, previous)
            db.session.commit()


def test_system_settings_saves_ai_stream_limit(admin_client, app):
    with app.app_context():
        previous = {key: SystemConfig.get(key) for key in SWITCH_KEYS}
        previous_limit = SystemConfig.get(AI_LIMIT_KEY)

    def _post(limit):
        data = {key: '1' for key in SWITCH_KEYS}
        data[AI_LIMIT_KEY] = limit
        return admin_client.post('/admin/system', data=data,
                                 headers={'X-CSRFToken': CSRF},
                                 follow_redirects=True)

    try:
        page = _post('5').get_data(as_text=True)
        assert '系统设置已保存' in page
        with app.app_context():
            assert SystemConfig.get(AI_LIMIT_KEY) == '5'
        html = admin_client.get('/admin/system').get_data(as_text=True)
        assert 'AI 流式并发上限' in html and 'value="5"' in html

        # 非法值：整单不落库（连开关也不改）
        with app.app_context():
            SystemConfig.set('admin_remote_enabled', 'false')
            db.session.commit()
        bad = _post('0').get_data(as_text=True)
        assert '1–64' in bad
        with app.app_context():
            assert SystemConfig.get(AI_LIMIT_KEY) == '5'
            assert SystemConfig.get_bool('admin_remote_enabled') is False

        # 留空 = 恢复部署默认
        _post('')
        with app.app_context():
            assert SystemConfig.get(AI_LIMIT_KEY) == ''
    finally:
        with app.app_context():
            for key, value in previous.items():
                if value is None:
                    SystemConfig.query.filter_by(key=key).delete(
                        synchronize_session=False)
                else:
                    SystemConfig.set(key, value)
            SystemConfig.query.filter_by(key=AI_LIMIT_KEY).delete(
                synchronize_session=False)
            if previous_limit is not None:
                SystemConfig.set(AI_LIMIT_KEY, previous_limit)
            db.session.commit()


# ── 大文件下载专用线程池 ─────────────────────────────────────
@pytest.fixture
def pool(app, monkeypatch, tmp_path):
    """每个用例独立的池状态：并发 1、阈值 1MB，结束关闭线程池。"""
    def _reset():
        executor = download_pool._executor
        if executor is not None:
            executor.shutdown(wait=True)
        download_pool._executor = None
        download_pool._slots = None

    _reset()
    monkeypatch.setitem(app.config, 'LARGE_DOWNLOAD_POOL_SIZE', 1)
    monkeypatch.setitem(app.config, 'LARGE_DOWNLOAD_THRESHOLD_MB', 1)
    big = tmp_path / 'big.bin'
    big.write_bytes(PAYLOAD)
    small = tmp_path / 'small.bin'
    small.write_bytes(b'x' * 1024)
    yield {'big': str(big), 'small': str(small)}
    _reset()


def _serve(app, path, headers=None, as_attachment=True):
    """在独立请求上下文中调用，返回 (响应, app_iter, environ)。"""
    from werkzeug.test import EnvironBuilder
    environ = EnvironBuilder(path='/', headers=headers or {}).get_environ()
    with app.request_context(environ):
        response = download_pool.send_large_download(
            path, conditional=True, as_attachment=as_attachment,
            download_name=os.path.basename(path))
    return response, response.get_app_iter(environ), environ


def _drain(app_iter):
    try:
        return b''.join(app_iter)
    finally:
        close = getattr(app_iter, 'close', None)
        if close is not None:
            close()


def test_small_or_inline_download_bypasses_pool(app, pool):
    response, app_iter, _ = _serve(app, pool['small'])
    assert response.status_code == 200
    assert _drain(app_iter) == b'x' * 1024
    assert download_pool._executor is None

    response, app_iter, _ = _serve(app, pool['big'], as_attachment=False)
    assert response.status_code == 200
    assert _drain(app_iter) == PAYLOAD
    assert download_pool._executor is None


def test_large_attachment_streams_through_pool_and_releases_slot(app, pool):
    response, app_iter, _ = _serve(app, pool['big'])
    assert response.status_code == 200
    assert response.content_length == len(PAYLOAD)
    assert response.headers.get('Accept-Ranges') == 'bytes'
    assert download_pool._slots._value == 0
    assert _drain(app_iter) == PAYLOAD
    assert download_pool._slots._value == 1


def test_waitress_file_wrapper_streams_and_releases_slot(app, pool):
    """与真实 Waitress 一致：服务器用 wsgi.file_wrapper 包装文件，只关 app_iter。"""
    from werkzeug.test import EnvironBuilder
    from waitress.buffers import ReadOnlyFileBasedBuffer

    environ = EnvironBuilder(path='/').get_environ()
    environ['wsgi.file_wrapper'] = ReadOnlyFileBasedBuffer
    with app.request_context(environ):
        response = download_pool.send_large_download(
            pool['big'], conditional=True, as_attachment=True,
            download_name='big.bin')
    app_iter = response.get_app_iter(environ)
    try:
        body = b''.join(app_iter)
    finally:
        app_iter.close()
    assert body == PAYLOAD
    assert download_pool._slots._value == 1


def test_large_attachment_supports_range_and_releases_slot(app, pool):
    response, app_iter, _ = _serve(app, pool['big'],
                                   headers={'Range': 'bytes=10-19'})
    assert response.status_code == 206
    assert response.headers['Content-Range'] == \
        f'bytes 10-19/{len(PAYLOAD)}'
    assert _drain(app_iter) == PAYLOAD[10:20]
    assert download_pool._slots._value == 1


def test_304_closes_reader_and_releases_slot(app, pool):
    response, app_iter, _ = _serve(
        app, pool['big'],
        headers={'If-Modified-Since': 'Wed, 01 Jan 2031 00:00:00 GMT'})
    assert response.status_code == 304
    assert _drain(app_iter) == b''
    assert download_pool._slots._value == 1


def test_saturated_pool_fails_fast_then_recovers(app, pool):
    response, app_iter, _ = _serve(app, pool['big'])
    assert response.status_code == 200
    rejected, _, _ = _serve(app, pool['big'])
    assert rejected.status_code == 503
    assert rejected.headers['Retry-After'] == '5'
    assert '稍后重试' in rejected.get_data(as_text=True)
    # 先释放名额，下一次下载恢复
    _drain(app_iter)
    assert download_pool._slots._value == 1
    ok, ok_iter, _ = _serve(app, pool['big'])
    assert ok.status_code == 200
    assert _drain(ok_iter) == PAYLOAD


def test_pool_disabled_by_zero_size(app, pool, monkeypatch):
    monkeypatch.setitem(app.config, 'LARGE_DOWNLOAD_POOL_SIZE', 0)
    response, app_iter, _ = _serve(app, pool['big'])
    assert response.status_code == 200
    assert _drain(app_iter) == PAYLOAD
    assert download_pool._executor is None


# ── Waitress 线程数部署参数 ─────────────────────────────────
def test_deploy_conf_value_read_update_roundtrip(tmp_path):
    """管理端写入走 update_deploy_conf_value：注释样例行就地替换、幂等。"""
    from app.config import read_deploy_conf_value, update_deploy_conf_value

    inst = tmp_path / 'instance'
    inst.mkdir()
    conf = inst / 'deploy.conf'
    conf.write_text('# waitress_threads=48\ncache_type=SimpleCache\n',
                    encoding='utf-8')

    assert read_deploy_conf_value('waitress_threads', str(tmp_path)) is None
    assert update_deploy_conf_value('waitress_threads', '64', str(tmp_path))
    assert read_deploy_conf_value('WAITRESS_THREADS', str(tmp_path)) == '64'
    text = conf.read_text(encoding='utf-8')
    assert '# waitress_threads' not in text, '注释样例行应被替换而非共存'
    assert 'cache_type=SimpleCache' in text, '其余配置原样保留'

    assert update_deploy_conf_value('waitress_threads', '96', str(tmp_path))
    assert conf.read_text(encoding='utf-8').count('waitress_threads=') == 1
    assert read_deploy_conf_value('waitress_threads', str(tmp_path)) == '96'


def test_deploy_conf_value_update_appends_missing_key(tmp_path):
    from app.config import read_deploy_conf_value, update_deploy_conf_value

    inst = tmp_path / 'instance'
    inst.mkdir()
    conf = inst / 'deploy.conf'
    conf.write_text('cache_type=SimpleCache\n', encoding='utf-8')

    assert update_deploy_conf_value('waitress_threads', '32', str(tmp_path))
    text = conf.read_text(encoding='utf-8')
    assert text.endswith('waitress_threads=32\n')
    assert 'cache_type=SimpleCache' in text
    assert read_deploy_conf_value('waitress_threads', str(tmp_path)) == '32'


def test_deploy_conf_value_update_preserves_crlf(tmp_path):
    """Windows 安装生成的 deploy.conf 是 CRLF，保存后不得整体改成 LF。"""
    from app.config import update_deploy_conf_value

    inst = tmp_path / 'instance'
    inst.mkdir()
    conf = inst / 'deploy.conf'
    conf.write_bytes(b'# waitress_threads=48\r\ncache_type=SimpleCache\r\n')

    assert update_deploy_conf_value('waitress_threads', '64', str(tmp_path))
    data = conf.read_bytes()
    assert b'waitress_threads=64\r\n' in data
    rest = data.replace(b'\r\n', b'')
    assert b'\n' not in rest and b'\r' not in rest


def test_deploy_conf_value_update_keeps_blank_lines(tmp_path):
    """替换只能吃掉目标行，不得把前面的空行/注释一并合并。"""
    from app.config import update_deploy_conf_value

    inst = tmp_path / 'instance'
    inst.mkdir()
    conf = inst / 'deploy.conf'
    conf.write_text('# 说明文字\n# waitress_threads=48\n\n'
                    'cache_type=SimpleCache\n', encoding='utf-8')

    assert update_deploy_conf_value('waitress_threads', '64', str(tmp_path))
    text = conf.read_text(encoding='utf-8')
    assert text == ('# 说明文字\nwaitress_threads=64\n\n'
                    'cache_type=SimpleCache\n')


@pytest.mark.parametrize('key,value', [
    ('bad key', '16'), ('waitress_threads', ''), ('waitress_threads', '1\nx=2'),
])
def test_deploy_conf_value_update_rejects_invalid(tmp_path, key, value):
    from app.config import update_deploy_conf_value

    assert update_deploy_conf_value(key, value, str(tmp_path)) is False
    assert not (tmp_path / 'instance' / 'deploy.conf').exists()


def test_waitress_threads_bounds_and_pool_scaling(app):
    """配置值在 8–128 内；连接池按线程数自动放大（锁死规划公式）。"""
    from app.config import (WAITRESS_THREADS_MAX, WAITRESS_THREADS_MIN)

    threads = app.config['WAITRESS_THREADS']
    assert WAITRESS_THREADS_MIN <= threads <= WAITRESS_THREADS_MAX
    options = app.config['SQLALCHEMY_ENGINE_OPTIONS']
    assert options['pool_size'] == max(40, math.ceil(threads * 5 / 6))
    assert options['max_overflow'] == max(20, math.ceil(threads * 5 / 12))
    assert options['pool_size'] + options['max_overflow'] >= threads, \
        '连接池上限不得少于线程数，否则线程内 DB 访问互相排队'


def test_deploy_int_rejects_above_maximum(monkeypatch):
    from app.config import _deploy_int

    monkeypatch.delenv('WAITRESS_THREADS', raising=False)
    assert _deploy_int({}, 'WAITRESS_THREADS', 'waitress_threads', 48,
                       minimum=8, maximum=128) == 48
    assert _deploy_int({'waitress_threads': '128'}, 'WAITRESS_THREADS',
                       'waitress_threads', 48, minimum=8,
                       maximum=128) == 128
    # 超过上限回退默认（此前只校验下限，129 会进入 Waitress）
    assert _deploy_int({'waitress_threads': '129'}, 'WAITRESS_THREADS',
                       'waitress_threads', 48, minimum=8,
                       maximum=128) == 48


def test_system_settings_saves_waitress_threads(admin_client, app,
                                                monkeypatch):
    """管理端保存/回显/校验；测试中不触碰真实 instance/deploy.conf。"""
    from app.blueprints import system_settings

    calls = []
    monkeypatch.setattr(
        system_settings, 'update_deploy_conf_value',
        lambda key, value, base_dir=None: calls.append((key, value)) or True)
    monkeypatch.setattr(
        system_settings, 'read_deploy_conf_value',
        lambda key, base_dir=None: '64')
    monkeypatch.delenv('WAITRESS_THREADS', raising=False)

    with app.app_context():
        previous = {key: SystemConfig.get(key) for key in SWITCH_KEYS}
        previous_limit = SystemConfig.get(AI_LIMIT_KEY)

    def _post(threads, include=True):
        data = {key: '1' for key in SWITCH_KEYS}
        data[AI_LIMIT_KEY] = ''
        if include:
            data['waitress_threads'] = threads
        return admin_client.post(
            '/admin/system', data=data, headers={'X-CSRFToken': CSRF},
            follow_redirects=True).get_data(as_text=True)

    try:
        page = _post('64')
        assert '系统设置已保存' in page
        assert '重启 ITstudy 服务后生效' in page
        assert calls[-1] == ('waitress_threads', '64')

        html = admin_client.get('/admin/system').get_data(as_text=True)
        assert 'Waitress 工作线程数' in html
        assert '<code>WAITRESS_THREADS</code>' in html
        assert 'value="64"' in html
        if int(app.config['WAITRESS_THREADS']) != 64:
            assert '已保存 64' in html and '待重启' in html

        # 非法值整单拒绝：不写 deploy.conf、开关也不落库
        with app.app_context():
            SystemConfig.set('admin_remote_enabled', 'false')
            db.session.commit()
        before = len(calls)
        for bad, expected in (('abc', '必须是整数'),
                              ('7', '8–128'),
                              ('129', '8–128')):
            page = _post(bad)
            assert expected in page
            assert len(calls) == before
        with app.app_context():
            assert SystemConfig.get_bool('admin_remote_enabled') is False
            assert SystemConfig.get(AI_LIMIT_KEY) == ''

        # 留空 = 恢复部署默认 48
        _post('')
        assert calls[-1] == ('waitress_threads', '48')

        # 字段缺省（旧表单）：不得改动 deploy.conf
        count = len(calls)
        _post('', include=False)
        assert len(calls) == count
        with app.app_context():
            assert SystemConfig.get(AI_LIMIT_KEY) == ''
    finally:
        with app.app_context():
            for key, value in previous.items():
                if value is None:
                    SystemConfig.query.filter_by(key=key).delete(
                        synchronize_session=False)
                else:
                    SystemConfig.set(key, value)
            SystemConfig.query.filter_by(key=AI_LIMIT_KEY).delete(
                synchronize_session=False)
            if previous_limit is not None:
                SystemConfig.set(AI_LIMIT_KEY, previous_limit)
            db.session.commit()
