# -*- coding: utf-8 -*-
"""DeepSeek 全家桶应用 API 接入回归（V6.1.0 · 2026-11-19）。

覆盖：
- 仅官方 api.deepseek.com + deepseek-flash 开启能力；
- Chat Completions 请求携带 deepseek_web_search / deepseek_read_url /
  safety_check；
- Files 上传白名单、多轮文件块回放；
- ASR / TTS 服务端代理（密钥不出服务端）；
- /api/ai/status 向前端暴露入口开关。
"""
import io
import json
import uuid

import pytest

from app import create_app
from app.blueprints.ai import (
    _deepseek_capabilities, _deepseek_root, _deepseek_tool_config,
    _parse_deepseek_files, _prepare_chat_context, _call_chat,
)
from app.extensions import cache, db
from app.models import AIConfig, AIChatMessage, Class, Student

CSRF = 'deepseek-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


class FakeResp:
    def __init__(self, body=b'', status=200):
        self.body = body
        self.status_code = status
        self.encoding = 'utf-8'
        self.headers = {}

    def iter_content(self, chunk_size=16384):
        if self.body:
            yield self.body

    def close(self):
        pass


def test_deepseek_capability_detection():
    assert _deepseek_root('https://api.deepseek.com') == 'https://api.deepseek.com'
    assert _deepseek_root('https://api.deepseek.com/v1') == 'https://api.deepseek.com'
    assert _deepseek_root('https://api.deepseek.com/anthropic') is None
    assert _deepseek_root('https://example.com/v1') is None
    cfg = {'provider': 'openai', 'api_url': 'https://api.deepseek.com/v1',
           'model': 'deepseek-flash'}
    assert _deepseek_capabilities(cfg) is not None
    assert _deepseek_capabilities(dict(cfg, model='deepseek-chat')) is None
    assert _deepseek_capabilities(dict(cfg, provider='anthropic')) is None
    tools = _deepseek_tool_config(
        dict(cfg, api_url='https://api.deepseek.com'), 'deepseek-flash',
        {'deepseek': {'web_search': True, 'read_url': False}})
    assert tools['web_search'] is True and tools['read_url'] is False
    assert tools['safety'] is True


def test_deepseek_chat_payload(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs.get('json')
        return FakeResp(json.dumps({
            'choices': [{'message': {'content': '好的'}, 'finish_reason': 'stop'}]
        }).encode('utf-8'))

    monkeypatch.setattr('app.blueprints.ai._safe_ai_request', fake_request)
    ok, content, status, stop, meta = _call_chat(
        'openai', 'sk-test', 'https://api.deepseek.com', 'deepseek-flash',
        [{'role': 'user', 'content': '今天有什么新闻'}], 512, 0.7,
        deepseek_options={'enabled': True, 'web_search': True,
                          'read_url': True, 'safety': True})
    assert ok and content == '好的'
    payload = captured['json']
    assert {'type': 'deepseek_web_search'} in payload['tools']
    assert {'type': 'deepseek_read_url'} in payload['tools']
    assert payload['safety_check'] == {'level': 'high'}
    assert meta == {'refusal': False, 'sources': []}


def test_deepseek_file_allowlist(app):
    actor = 'student:12345'
    with app.app_context():
        cache.delete('deepseek_files:' + actor)
        files, err = _parse_deepseek_files(
            [{'id': 'file-api-abcdefgh1234', 'name': 'a.pdf'}], actor)
        assert err == '文件已失效或不属于当前会话，请重新上传'
        cache.set('deepseek_files:' + actor, ['file-api-abcdefgh1234'], timeout=60)
        files, err = _parse_deepseek_files(
            [{'id': 'file-api-abcdefgh1234', 'name': 'a.pdf',
              'purpose': 'rich_layout_recognition'}], actor)
        assert err is None and files[0]['id'] == 'file-api-abcdefgh1234'
        files, err = _parse_deepseek_files(
            [{'id': 'file-api-forged12345678', 'name': 'b.pdf'}], actor)
        assert err == '文件已失效或不属于当前会话，请重新上传'


def _set_deepseek_config(app):
    with app.app_context():
        cfg = AIConfig.query.first()
        created = cfg is None
        if created:
            cfg = AIConfig()
            db.session.add(cfg)
        saved = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                 cfg._api_key, cfg.provider)
        cfg.enabled = True
        cfg.config_mode = 'admin'
        cfg.provider = 'openai'
        cfg.api_url = 'https://api.deepseek.com'
        cfg.model = 'deepseek-flash'
        cfg.api_key = 'sk-deepseek-test'
        db.session.commit()
        return created, saved


def _restore_config(app, created, saved):
    with app.app_context():
        cfg = AIConfig.query.first()
        if cfg is None:
            return
        if created:
            db.session.delete(cfg)
        else:
            (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
             cfg._api_key, cfg.provider) = saved
        db.session.commit()


def test_deepseek_upload_asr_tts_and_status(app, monkeypatch):
    created, saved = _set_deepseek_config(app)
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__ds_cls_{suffix}')
        stu = Student(name='深度求索学生', student_number=f'__ds_{suffix}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.commit()
        cls_id, stu_id = cls.id, stu.id
    client = _client(app, student_id=stu_id, student_name='深度求索学生')

    def fake_request(method, url, **kwargs):
        if url.endswith('/files'):
            return FakeResp(json.dumps({
                'id': 'file-api-testfile1234', 'object': 'file',
                'bytes': 8, 'filename': 'report.pdf',
                'purpose': 'rich_layout_recognition',
            }).encode('utf-8'))
        if url.endswith('/v1/tools/asr'):
            return FakeResp(json.dumps({
                'request_id': 'r1', 'text': '上海今天天气怎么样？',
                'duration_ms': 3200,
            }).encode('utf-8'))
        if url.endswith('/v1/tools/tts'):
            return FakeResp(b'RIFF0000WAVEfmt ')
        raise AssertionError(url)

    monkeypatch.setattr('app.blueprints.ai._safe_ai_request', fake_request)
    try:
        # 能力开关
        status = client.get('/api/ai/status').get_json()
        assert status['deepseek_tools'] is True
        # 文件上传
        upload = client.post(
            '/api/ai/deepseek/files',
            data={'file': (io.BytesIO(b'%PDF-1.4'), 'report.pdf')},
            content_type='multipart/form-data',
            headers={'X-CSRFToken': CSRF})
        assert upload.status_code == 200, upload.get_data(as_text=True)
        body = upload.get_json()
        assert body['success'] is True
        assert body['file']['id'] == 'file-api-testfile1234'
        # ASR
        asr = client.post(
            '/api/ai/deepseek/asr',
            data={'file': (io.BytesIO(b'RIFF....WAVE'), 'speech.wav')},
            content_type='multipart/form-data',
            headers={'X-CSRFToken': CSRF})
        assert asr.status_code == 200
        assert asr.get_json()['text'].startswith('上海今天天气')
        # TTS 流式音频
        tts = client.post('/api/ai/deepseek/tts',
                          json={'text': '你好，我是 DeepSeek。', 'voice_id': 'stella'},
                          headers={'X-CSRFToken': CSRF})
        assert tts.status_code == 200
        assert 'audio/wav' in tts.headers['Content-Type']
        assert tts.get_data().startswith(b'RIFF')
        # 多轮：带 file_id 的请求构建 file 块，并随历史回放
        with app.test_request_context(
                '/api/ai/chat', method='POST',
                json={'message': '总结这份文件',
                      'files': [{'id': 'file-api-testfile1234',
                                 'name': 'report.pdf',
                                 'purpose': 'rich_layout_recognition'}],
                      'page_content': ''}):
            from flask import session as flask_session
            flask_session['student_id'] = stu_id
            conv, err = _prepare_chat_context()
            assert err is None and conv is not None
            last = conv['messages'][-1]
            assert isinstance(last['content'], list)
            assert last['content'][0] == {
                'type': 'file', 'file_id': 'file-api-testfile1234'}
            assert conv['deepseek']['safety'] is True
        with app.test_request_context(
                '/api/ai/chat', method='POST',
                json={'message': '再详细一点', 'page_content': '',
                      'session_id': conv['session_id']}):
            from flask import session as flask_session
            flask_session['student_id'] = stu_id
            conv2, err = _prepare_chat_context()
            assert err is None and conv2 is not None
            history_blocks = [
                m['content'] for m in conv2['messages']
                if m.get('role') == 'user' and isinstance(m.get('content'), list)
            ]
            assert any(block[0].get('type') == 'file'
                       for block in history_blocks)
        # 非官方地址：状态入口关闭
        with app.app_context():
            cfg = AIConfig.query.first()
            cfg.api_url = 'https://example.com/v1'
            db.session.commit()
        assert client.get('/api/ai/status').get_json()['deepseek_tools'] is False
    finally:
        with app.app_context():
            AIChatMessage.query.filter(
                AIChatMessage.actor == f'student:{stu_id}').delete(
                    synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
            db.session.commit()
        cache.delete('deepseek_files:student:' + str(stu_id))
        _restore_config(app, created, saved)
