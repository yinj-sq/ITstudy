"""课件公开开关回归测试（courseware_public_enabled）

默认公开：未登录可浏览 /study 与课件文件直链。
关闭后：/study、/study/preview 重定向登录；课件文件直链 403。
"""
import pytest

from app import create_app
from app.extensions import db
from app.models import SystemConfig


def _set_switch(value):
    """设置开关并 commit（SystemConfig.set 不 commit，由调用方统一提交）"""
    SystemConfig.set('courseware_public_enabled', value)
    db.session.commit()


def _delete_switch():
    """删除开关记录并失效缓存（恢复默认公开行为）"""
    row = db.session.get(SystemConfig, 'courseware_public_enabled')
    if row:
        db.session.delete(row)
        db.session.commit()
    SystemConfig._invalidate_cache()


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        _delete_switch()


def test_courseware_default_public(app):
    """开关未设置（默认公开）：匿名可访问 /study。"""
    with app.app_context():
        _delete_switch()
    client = app.test_client()
    resp = client.get('/study', follow_redirects=False)
    assert resp.status_code == 200


def test_courseware_closed_blocks_anonymous(app):
    """开关关闭：匿名访问 /study 重定向登录、课件直链 403。"""
    with app.app_context():
        _set_switch('false')
    client = app.test_client()
    resp = client.get('/study', follow_redirects=False)
    assert resp.status_code == 302, '关闭后匿名 /study 应重定向登录'
    assert resp.headers.get('Location', '') == '/', '应重定向到登录页 /'
    # 课件文件直链兜底：任何 /static/uploads/ 下路径匿名访问一律 403
    resp = client.get('/static/uploads/reg-courseware/index.html')
    assert resp.status_code == 403, '关闭后匿名课件直链应 403'


def test_courseware_closed_allows_login_user(app):
    """开关关闭后登录用户不受影响。"""
    from app.models import Student as _Stu
    with app.app_context():
        _set_switch('false')
        stu = _Stu(name='开关学生', student_number='SW-1')
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        stu_id = stu.id
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['student_id'] = stu_id
            sess['student_name'] = '开关学生'
            sess['student_class_id'] = None
            sess['csrf_token'] = 't'
        resp = client.get('/study', follow_redirects=False)
        assert resp.status_code == 200, '登录用户访问 /study 不应被开关拦截'
    finally:
        with app.app_context():
            _Stu.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()


def test_courseware_reopen_restores_public(app):
    """开关重新开启后匿名访问恢复。"""
    with app.app_context():
        _set_switch('true')
    client = app.test_client()
    resp = client.get('/study', follow_redirects=False)
    assert resp.status_code == 200
