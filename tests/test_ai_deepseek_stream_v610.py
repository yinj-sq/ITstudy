# -*- coding: utf-8 -*-
"""DeepSeek 流式事件透传回归（V6.1.0 · 2026-11-19）。"""
import json
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import AIChatMessage, AIConfig, Class, Student

CSRF = 'deepseek-stream-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


class FakeStream:
    def __init__(self, lines):
        self.lines = lines

    def iter_lines(self, decode_unicode=True):
        for line in self.lines:
            yield line

    def close(self):
        pass


def _setup(app):
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
        cfg.api_key = 'sk-stream-test'
        suffix = uuid.uuid4().hex[:8]
        cls = Class(name=f'__ds_st_cls_{suffix}')
        stu = Student(name='流式学生', student_number=f'__ds_st_{suffix}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.commit()
        return created, saved, cls.id, stu.id


def _teardown(app, created, saved, cls_id, stu_id):
    with app.app_context():
        AIChatMessage.query.filter(
            AIChatMessage.actor == f'student:{stu_id}').delete(
                synchronize_session=False)
        Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
        Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
        cfg = AIConfig.query.first()
        if cfg is not None:
            if created:
                db.session.delete(cfg)
            else:
                (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model,
                 cfg._api_key, cfg.provider) = saved
        db.session.commit()


def test_stream_deepseek_events_and_refusal(app, monkeypatch):
    created, saved, cls_id, stu_id = _setup(app)
    client = _client(app, student_id=stu_id, student_name='流式学生')
    try:
        def make_lines(refusal=False):
            lines = [
                'data: ' + json.dumps({'choices': [{
                    'server_tool_event': {
                        'type': 'started',
                        'call': {'type': 'deepseek_web_search', 'kind': 'search',
                                 'action': {'type': 'search', 'queries': ['x']}},
                    },
                    'delta': {}}]}),
                'data: ' + json.dumps({'choices': [{'delta': {'content': '你好'}}]}),
                'data: ' + json.dumps({'choices': [{'delta': {
                    'annotations': [{'type': 'url_citation', 'url_citation': {
                        'url': 'https://example.com/a', 'title': '示例'}}],
                    'server_tool_calls': [{'calls': [{'sources': [
                        {'url': 'https://example.com/a', 'title': '示例'}]}]}],
                }, 'finish_reason': 'content_filter' if refusal else 'stop'}]}),
                'data: [DONE]',
            ]
            return lines

        calls = {'n': 0}

        def fake_call_chat(*args, **kwargs):
            calls['n'] += 1
            return True, FakeStream(make_lines(refusal=calls['n'] == 2)), 200, None, None

        monkeypatch.setattr('app.blueprints.ai._call_chat', fake_call_chat)
        first = client.post('/api/ai/chat/stream',
                            json={'message': '今天有什么新闻', 'page_content': ''},
                            headers={'X-CSRFToken': CSRF})
        text = first.get_data(as_text=True)
        events = []
        for line in text.splitlines():
            if line.startswith('data: '):
                try:
                    events.append(json.loads(line[6:]))
                except ValueError:
                    pass
        labels = [e.get('tool_event', {}).get('label', '') for e in events
                  if e.get('tool_event')]
        assert any('正在联网搜索' in label for label in labels)
        assert any(e.get('sources') for e in events)
        assert any(e.get('done') is True and e.get('refusal') is False
                   for e in events)

        second = client.post('/api/ai/chat/stream',
                             json={'message': '第二条', 'page_content': ''},
                             headers={'X-CSRFToken': CSRF})
        text2 = second.get_data(as_text=True)
        events2 = []
        for line in text2.splitlines():
            if line.startswith('data: '):
                try:
                    events2.append(json.loads(line[6:]))
                except ValueError:
                    pass
        assert any(e.get('refusal') is True for e in events2)
        assert any('内容未通过安全审核' in (e.get('message') or '')
                   for e in events2)
        with app.app_context():
            rows = AIChatMessage.query.filter_by(
                actor=f'student:{stu_id}', role='assistant').all()
            # 第一条正常回答落库，拒答的一条不得落库
            assert len(rows) == 1 and rows[0].content == '你好'
    finally:
        _teardown(app, created, saved, cls_id, stu_id)
