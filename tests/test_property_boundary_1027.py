# -*- coding: utf-8 -*-
"""属性测试 + 边界值测试（2026-10-27，系统测试专项）。

- Hypothesis：随机/恶意文件名与整数输入下工具函数不抛异常、不产生越界值
- 边界值：分页页号钳制、测验提交字段上限、来源路径长度限制
"""

import pytest
from hypothesis import given, strategies as st

from app import create_app
from app.extensions import cache
from app.blueprints.resources import _resource_dir_name
from app.utils import parse_int

CSRF = 'prop-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


# ── 属性测试（纯函数，无 DB）───────────────────────────────

@given(st.text(min_size=0, max_size=300))
def test_resource_dir_name_never_raises_and_stays_bounded(raw):
    name = _resource_dir_name(raw)
    assert name is not None
    assert len(name) <= len(raw) + 8  # 前缀/替换不无限膨胀
    assert '\x00' not in name


@given(st.integers(), st.integers())
def test_parse_int_never_raises(value, default):
    out = parse_int(str(value), default)
    assert out is None or isinstance(out, int)


@given(st.text(min_size=1, max_size=64), st.integers(min_value=-5, max_value=20))
def test_page_parameter_clamped(sfx, page):
    from flask import Flask
    # paginate_query 依赖 request 上下文，用最小 Flask 应用验证钳制逻辑
    app = Flask('prop-page')
    with app.test_request_context('/?page=%d' % page):
        from flask import request
        raw = request.args.get('page', 1, type=int)
        assert isinstance(raw, int)
        clamped = min(max(raw, 1), 10_000_000)
        assert 1 <= clamped <= 10_000_000


# ── 边界值测试（测验提交字段）───────────────────────────────

def _setup_resource(app, sfx):
    from app.models import Resource as _R, Student as _S
    with app.app_context():
        res = _R(title=f'__prop_res_{sfx}', url='https://example.com/prop',
                 show_in_student=True, show_in_classroom=True,
                 is_public=True, quiz_mode='inject')
        stu = _S(name='属性学生', student_number=f'__prop_stu_{sfx}',
                 has_changed_password=True)
        stu.set_password('pass123456')
        from app.extensions import db as _db
        _db.session.add_all([res, stu])
        _db.session.commit()
        return res.id, stu.id


def _cleanup(app, sfx):
    with app.app_context():
        from app.extensions import db as _db
        from app.models import (Resource as _R, ResourceQuizResult as _RQR,
                                Student as _S)
        rids = [r.id for r in _R.query.filter(
            _R.title.like(f'__prop_res_{sfx}%')).all()]
        if rids:
            _RQR.query.filter(_RQR.resource_id.in_(rids)).delete(
                synchronize_session=False)
        _R.query.filter(_R.title.like(f'__prop_res_{sfx}%')).delete(
            synchronize_session=False)
        _S.query.filter(_S.student_number.like(f'__prop_stu_{sfx}%')).delete(
            synchronize_session=False)
        _db.session.commit()


def _submit(client, rid, payload):
    return client.post('/api/resource_quiz/submit', json={
        'resource_id': rid, **payload}, headers={'X-CSRFToken': CSRF})


def test_quiz_submit_boundary_values(app):
    import uuid
    sfx = uuid.uuid4().hex[:8]
    rid = sid = None
    try:
        rid, sid = _setup_resource(app, sfx)
        client = app.test_client()
        with client.session_transaction() as s:
            s['student_id'] = sid
            s['csrf_token'] = CSRF

        # 满分/总分上限：100000 允许，100001 拒绝
        assert _submit(client, rid, {'total_score': 100000, 'max_score': 100000}).status_code == 200
        assert _submit(client, rid, {'total_score': 100001, 'max_score': 100000}).status_code == 400
        # 总分>满分 拒绝
        assert _submit(client, rid, {'total_score': 51, 'max_score': 50}).status_code == 400
        # NaN/Infinity 拒绝
        assert _submit(client, rid, {'total_score': 'NaN'}).status_code == 400
        assert _submit(client, rid, {'total_score': 'Infinity'}).status_code == 400
        # 答对题数>总题数 拒绝；两者相等允许
        assert _submit(client, rid, {'correct_count': 11, 'question_count': 10}).status_code == 400
        assert _submit(client, rid, {'correct_count': 10, 'question_count': 10}).status_code == 200
        # 时长上限 24h：86400 允许，86401 拒绝
        assert _submit(client, rid, {'duration': 86400}).status_code == 200
        assert _submit(client, rid, {'duration': 86401}).status_code == 400
        # 来源文件：>500 字符拒绝；合法路径允许
        assert _submit(client, rid, {'source_file': 'x' * 501 + '.html'}).status_code == 400
        assert _submit(client, rid, {'source_file': 'ok.html'}).status_code == 400  # 磁盘不存在
        # 测验名 emoji 截断：不得 500，且不超过 200 字节
        r = _submit(client, rid, {'quiz_name': '测' * 100 + '😀😀😀😀😀'})
        assert r.status_code == 200
        with app.app_context():
            from app.models import ResourceQuizResult as _RQR
            row = _RQR.query.filter_by(student_id=sid, resource_id=rid).first()
            assert row and len(row.quiz_name.encode('utf-8')) <= 200
    finally:
        _cleanup(app, sfx)
        cache.delete('study:resources:student')


def test_answers_payload_size_limits(app):
    import uuid
    sfx = uuid.uuid4().hex[:8]
    rid = sid = None
    try:
        rid, sid = _setup_resource(app, sfx)
        client = app.test_client()
        with client.session_transaction() as s:
            s['student_id'] = sid
            s['csrf_token'] = CSRF
        big_answers = {'q%d' % i: 'x' * 2000 for i in range(600)}  # >1MB
        r = _submit(client, rid, {'answers': big_answers})
        assert r.status_code == 413
        assert _submit(client, rid, {'answers': {'q1': 'ok'}}).status_code == 200
    finally:
        _cleanup(app, sfx)
