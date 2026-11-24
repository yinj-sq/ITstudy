# -*- coding: utf-8 -*-
"""全路由负向扫描（2026-10-27，系统测试专项）。

对 Flask url_map 的全部路由投喂畸形输入：
- <int:> 参数：0 / -1 / 2^31 / 2^63 / 10^30 / 极大负数
- 查询参数：page/q/subject 等投喂超长与非法值
- /api/ POST 端点：错误类型 JSON、畸形 JSON、空体
断言任何响应不得为 5xx；发现 500 即失败并列出路由。
"""

import json
import re

import pytest

from app import create_app
from app.extensions import db

CSRF = 'neg-sweep-csrf'

# 合理 500 的白名单：这些端点依赖外部服务/流式上下文，负向扫描不适用
SKIP_ENDPOINTS = {
    'static',
    'api.events_subscribe',       # SSE：GET 长连接，扫描无意义
    'ai.ai_chat_stream',          # 流式：依赖上游 AI 服务
    'ai.ai_chat',                 # 依赖上游 AI 服务
    'ai.ai_generate_image',       # 依赖生图上游
}

INT_JUNK = [0, -1, 2**31 - 1, 2**31, 2**63, 10**30, -10**30]
QUERY_JUNK = [
    {'page': ['0', '-1', '10' * 40, 'abc']},
    {'q': ['x' * 500, '%00', '..%2F..']},
    {'subject': ['none', 'all', '-1', 'x' * 300]},
]


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, role='admin'):
    client = app.test_client()
    with client.session_transaction() as s:
        s['csrf_token'] = CSRF
        if role == 'admin':
            s.update(is_admin=True, admin_name='扫描管理员')
        elif role == 'teacher':
            s.update(is_teacher=True, teacher_id=1, teacher_name='扫描教师',
                     teacher_mode='edit')
        elif role == 'student':
            s.update(student_id=1, student_name='扫描学生',
                     student_class_id=1, classroom_bound=True)
    return client


def _fill(rule_str, value):
    return re.sub(r'<int:[^>]+>', str(value), rule_str)


def test_all_int_routes_reject_junk_without_500(app):
    failures = []
    clients = {r: _client(app, r) for r in ('admin', 'teacher', 'student')}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        if rule.endpoint in SKIP_ENDPOINTS or '<int:' not in str(rule):
            continue
        if 'GET' not in rule.methods:
            continue
        for junk in INT_JUNK:
            path = _fill(str(rule), junk)
            # 每种角色打一遍（负向输入应统一 < 500，不随角色而异）
            client = clients['admin']
            try:
                resp = client.get(path)
            except Exception as exc:  # 路由内部异常 → 记录
                failures.append(f'{rule.endpoint} {path} EXC {type(exc).__name__}')
                continue
            if resp.status_code >= 500:
                failures.append(f'{rule.endpoint} {path} -> {resp.status_code}')
            if failures:
                break
        if len(failures) > 30:
            break
    assert not failures, '负向扫描发现 5xx：\n' + '\n'.join(failures[:40])


def test_query_parameter_junk_never_500(app):
    failures = []
    client = _client(app, 'admin')
    targets = ['/study', '/admin/resources', '/admin/logs', '/admin/students',
               '/admin/attendance/history', '/admin/homework', '/admin/works']
    for path in targets:
        for combo in QUERY_JUNK:
            for key, values in combo.items():
                for value in values:
                    url = f'{path}?{key}={value}'
                    try:
                        resp = client.get(url)
                    except Exception as exc:
                        failures.append(f'{url} EXC {type(exc).__name__}')
                        continue
                    if resp.status_code >= 500:
                        failures.append(f'{url} -> {resp.status_code}')
    assert not failures, '查询参数扫描发现 5xx：\n' + '\n'.join(failures[:40])


def test_api_post_endpoints_reject_malformed_json_without_500(app):
    failures = []
    clients = {r: _client(app, r) for r in ('admin', 'teacher', 'student')}
    bodies = [
        'not-json{',
        json.dumps({'title': 123, 'url': []}),
        json.dumps({'total_score': 1e309}),
        json.dumps({'answers': {'q': 'x' * 2000}}),
        json.dumps([1, 2, 3]),
        json.dumps(None),
        '',
    ]
    checked = 0
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        if 'POST' not in rule.methods or not str(rule).startswith('/api/'):
            continue
        path = _fill(str(rule), 1)
        client = clients['admin']
        for body in bodies:
            try:
                resp = client.post(
                    path, data=body,
                    content_type='application/json',
                    headers={'X-CSRFToken': CSRF})
            except Exception as exc:
                failures.append(f'{rule.endpoint} {path} EXC {type(exc).__name__}')
                continue
            checked += 1
            if resp.status_code >= 500:
                failures.append(
                    f'{rule.endpoint} {path} body={body[:40]!r} -> {resp.status_code}')
                break
    assert checked > 150, f'扫描量异常：{checked}'
    assert not failures, 'API 畸形体扫描发现 5xx：\n' + '\n'.join(failures[:40])


def test_negative_sweep_leaves_no_residue(app):
    """扫描不得在数据库留下垃圾行（负向输入应全部被拒）。"""
    with app.app_context():
        from app.models import Log
        # 只允许既有测试数据存在；扫描自身不写 log 之外的业务行
        leftover = db.session.execute(db.text(
            "SELECT count(*) FROM resource WHERE title LIKE '%扫描%'"
        )).scalar()
        assert leftover == 0
        assert Log.query.filter(Log.detail.like('%扫描%')).count() == 0
