# -*- coding: utf-8 -*-
"""登录锁定与密码重置解锁回归（2026-11-04）。

覆盖：
- 连续失败封锁时长统一为 300 秒（不再 300→600→1200→2400 升级）；
- 管理员单个/批量重置学生密码后立即清除学号、姓名维度及 IP 维度封锁，
  学生拿到新密码可马上重新登录；
- API 429 返回 retry_after，HTML/SPA 提示信息显示倒计时。
"""
import pathlib
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, ClassroomSession, Student

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSRF = 'login-lock-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None, json=None, ip=None):
    kwargs = {'headers': {'X-CSRFToken': CSRF}}
    if data is not None:
        data = dict(data)
        data.setdefault('csrf_token', CSRF)
        kwargs['data'] = data
    if json is not None:
        kwargs['json'] = json
    if ip:
        kwargs['environ_base'] = {'REMOTE_ADDR': ip}
    return client.post(path, **kwargs)


def _mk_student(sfx, idx, ip):
    cls = Class(name=f'__ll_cls_{sfx}_{idx}')
    stu = Student(name=f'__ll_stu_{idx}_{sfx}',
                  student_number=f'__ll_num_{idx}_{sfx}',
                  student_class=cls.name, ip_address=ip,
                  has_changed_password=True)
    stu.set_password('pass123456')
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.commit()
    return cls, stu


def _del_students(ids):
    with_class = []
    with db.session.no_autoflush:
        for sid in ids:
            stu = db.session.get(Student, sid)
            if stu:
                with_class.append(stu.class_id)
        Student.query.filter(Student.id.in_(ids)).delete(
            synchronize_session=False)
        Class.query.filter(Class.id.in_(with_class)).delete(
            synchronize_session=False)
        db.session.commit()


def test_block_seconds_fixed_300():
    from app.utils import _block_seconds
    assert {_block_seconds(i) for i in range(5)} == {300}


def test_html_single_reset_clears_throttle(app):
    from app.utils import (student_login_blocked_seconds,
                           student_login_register_failure,
                           student_login_clear_throttle)
    sfx = uuid.uuid4().hex[:8]
    ip = '203.0.113.241'
    with app.app_context():
        cls, stu = _mk_student(sfx, 1, ip)
        sid, number, name = stu.id, stu.student_number, stu.name
        cls_id = cls.id
    try:
        for _ in range(8):
            student_login_register_failure(ip, number)
            student_login_register_failure(ip, name)
        assert student_login_blocked_seconds(ip, number) > 0
        assert student_login_blocked_seconds(ip, name) > 0

        admin = _client(app, is_admin=True)
        resp = _post(admin, f'/admin/students/{sid}/reset-password',
                     {'new_password': 'newpass123'})
        assert resp.status_code in (302, 303)
        assert student_login_blocked_seconds(ip, number) == 0
        assert student_login_blocked_seconds(ip, name) == 0
        with app.app_context():
            stu = db.session.get(Student, sid)
            assert stu.check_password('newpass123')
            assert stu.has_changed_password is False
    finally:
        student_login_clear_throttle(number, name, [ip])
        with app.app_context():
            _del_students([sid])
            ClassroomSession.query.filter_by(class_id=cls_id).delete(
                synchronize_session=False)
            db.session.commit()


def test_api_single_reset_clears_throttle(app):
    """失败 IP 与最近登录 IP/管理员 IP 都不同：仍须凭失败 IP 索引解锁。"""
    from app.utils import (student_login_blocked_seconds,
                           student_login_register_failure,
                           student_login_clear_throttle)
    sfx = uuid.uuid4().hex[:8]
    last_ip = '203.0.113.250'
    fail_ip = '198.51.100.25'
    with app.app_context():
        cls, stu = _mk_student(sfx, 2, last_ip)
        sid, number, name = stu.id, stu.student_number, stu.name
        cls_id = cls.id
    try:
        for _ in range(8):
            student_login_register_failure(fail_ip, number)
        assert student_login_blocked_seconds(fail_ip, number) > 0
        admin = _client(app, is_admin=True)
        resp = _post(admin, f'/api/management/students/{sid}/reset-password',
                     json={'new_password': 'newpass123'})
        assert resp.status_code == 200
        assert student_login_blocked_seconds(fail_ip, number) == 0
        assert student_login_blocked_seconds(last_ip, number) == 0
        assert student_login_blocked_seconds(fail_ip, name) == 0
    finally:
        student_login_clear_throttle(number, name, [last_ip, fail_ip])
        with app.app_context():
            _del_students([sid])
            ClassroomSession.query.filter_by(class_id=cls_id).delete(
                synchronize_session=False)
            db.session.commit()


def test_batch_reset_clears_all_throttles(app):
    from app.utils import (student_login_blocked_seconds,
                           student_login_register_failure,
                           student_login_clear_throttle)
    sfx = uuid.uuid4().hex[:8]
    ip1, ip2 = '203.0.113.243', '203.0.113.244'
    with app.app_context():
        _, s1 = _mk_student(sfx, 3, ip1)
        _, s2 = _mk_student(sfx, 4, ip2)
        id1, id2 = s1.id, s2.id
        n1, name1 = s1.student_number, s1.name
        n2, name2 = s2.student_number, s2.name
        cls_ids = [s1.class_id, s2.class_id]
    try:
        for _ in range(8):
            student_login_register_failure(ip1, n1)
            student_login_register_failure(ip2, name2)
        assert student_login_blocked_seconds(ip1, n1) > 0
        assert student_login_blocked_seconds(ip2, name2) > 0
        admin = _client(app, is_admin=True)
        resp = _post(admin, '/api/management/students/batch-reset-password',
                     json={'ids': [id1, id2], 'new_password': 'newpass123'})
        assert resp.status_code == 200
        assert req_ok(resp)
        assert student_login_blocked_seconds(ip1, n1) == 0
        assert student_login_blocked_seconds(ip1, name1) == 0
        assert student_login_blocked_seconds(ip2, n2) == 0
        assert student_login_blocked_seconds(ip2, name2) == 0
    finally:
        student_login_clear_throttle(n1, name1, [ip1])
        student_login_clear_throttle(n2, name2, [ip2])
        with app.app_context():
            _del_students([id1, id2])
            ClassroomSession.query.filter(ClassroomSession.class_id.in_(
                cls_ids)).delete(synchronize_session=False)
            db.session.commit()


def req_ok(resp):
    data = resp.get_json() or {}
    return bool(data.get('success'))


def test_html_batch_reset_clears_all_throttles(app):
    from app.utils import (student_login_blocked_seconds,
                           student_login_register_failure,
                           student_login_clear_throttle)
    sfx = uuid.uuid4().hex[:8]
    ip1, ip2 = '203.0.113.246', '203.0.113.247'
    with app.app_context():
        _, s1 = _mk_student(sfx, 5, ip1)
        _, s2 = _mk_student(sfx, 6, ip2)
        id1, id2 = s1.id, s2.id
        n1, name1 = s1.student_number, s1.name
        n2, name2 = s2.student_number, s2.name
        cls_ids = [s1.class_id, s2.class_id]
    try:
        for _ in range(8):
            student_login_register_failure(ip1, name1)
            student_login_register_failure(ip2, n2)
        assert student_login_blocked_seconds(ip1, name1) > 0
        assert student_login_blocked_seconds(ip2, n2) > 0
        admin = _client(app, is_admin=True)
        resp = _post(admin, '/admin/students/batch-reset-password', {
            'ids': f'{id1},{id2}', 'new_password': 'newpass123'})
        assert resp.status_code in (302, 303)
        assert student_login_blocked_seconds(ip1, n1) == 0
        assert student_login_blocked_seconds(ip1, name1) == 0
        assert student_login_blocked_seconds(ip2, n2) == 0
        assert student_login_blocked_seconds(ip2, name2) == 0
    finally:
        student_login_clear_throttle(n1, name1, [ip1])
        student_login_clear_throttle(n2, name2, [ip2])
        with app.app_context():
            _del_students([id1, id2])
            ClassroomSession.query.filter(ClassroomSession.class_id.in_(
                cls_ids)).delete(synchronize_session=False)
            db.session.commit()


def test_api_login_429_has_retry_after(app):
    from app.utils import (student_login_blocked_seconds,
                           student_login_clear_throttle)
    sfx = uuid.uuid4().hex[:8]
    ip = '203.0.113.245'
    account = f'__ll_ghost_{sfx}'
    cls_id = None
    try:
        with app.app_context():
            cls = Class(name=f'__ll_ghost_cls_{sfx}')
            db.session.add(cls)
            db.session.flush()
            db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
            db.session.commit()
            cls_id = cls.id
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
        client = _client(app)
        for _ in range(8):
            resp = _post(client, '/api/auth/login', json={
                'student_number': account, 'password': 'wrongpass'}, ip=ip)
            assert resp.status_code == 401
        resp = _post(client, '/api/auth/login', json={
            'student_number': account, 'password': 'wrongpass'}, ip=ip)
        assert resp.status_code == 429
        data = resp.get_json()
        assert data['retry_after'] > 0
        assert str(data['retry_after']) in data['message']
        assert student_login_blocked_seconds(ip, account) > 0
    finally:
        student_login_clear_throttle(account, '', [ip])
        if cls_id:
            with app.app_context():
                ClassroomSession.query.filter_by(class_id=cls_id).delete(
                    synchronize_session=False)
                Class.query.filter_by(id=cls_id).delete(
                    synchronize_session=False)
                db.session.commit()
                from app.blueprints.auth import invalidate_active_class_cache
                invalidate_active_class_cache()


def test_countdown_ui_wired():
    base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'flash-message' in base
    assert '秒后再试' in base and 'setInterval' in base
    index = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    assert 'utils/login-countdown.js' in index
    util = (ROOT / 'frontend' / 'utils' /
            'login-countdown.js').read_text(encoding='utf-8')
    assert 'useLoginCountdown' in util
    assert 'remaining.value' in util
    for name in ('StudentLogin.js', 'AdminLogin.js'):
        src = (ROOT / 'frontend' / 'views' / name).read_text(
            encoding='utf-8')
        assert 'useLoginCountdown' in src
        assert 'countdown.remaining' in src
