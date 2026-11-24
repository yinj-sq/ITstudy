# -*- coding: utf-8 -*-
"""站点 favicon 回归（2026-10-20 8081 实测发现根路径 404）。"""
from app import create_app


def test_root_favicon_is_served():
    app = create_app()
    client = app.test_client()
    resp = client.get('/favicon.ico')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/x-icon'
    assert resp.data[:4] == b'\x00\x00\x01\x00'
    resp.close()


def test_static_favicon_is_served():
    app = create_app()
    client = app.test_client()
    resp = client.get('/static/favicon.ico')
    assert resp.status_code == 200
    assert resp.mimetype == 'image/x-icon'
    resp.close()
