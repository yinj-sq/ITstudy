# -*- coding: utf-8 -*-
"""静态私有目录的 Windows 路径语义回归（2026-10-19）。

背景：鉴权钩子按 URL 原样大小写做前缀/归属判断，而 Windows NTFS 大小写
不敏感、Win32 还会剥离段尾点/空格并解析 8.3 短名——`/static/UPLOADS/...`
可绕过 `_protect_private_uploads` 直接匿名读取私有文件。本用例在真实静态
目录中放一个临时文件，断言大小写/别名变体全部 403，且响应带 no-store。
"""
import os
import shutil
import uuid

import pytest

from app import create_app
from app.utils import has_win_path_alias

SID = '990001'


@pytest.fixture(scope='module')
def app():
    return create_app()


def test_has_win_path_alias():
    assert has_win_path_alias('/static/uploads/a/file.txt.') is True
    assert has_win_path_alias('/static/uploads/a/file.txt ') is True
    assert has_win_path_alias('/static/uploads/a/file.txt::$DATA') is True
    assert has_win_path_alias('/static/uploads/CLOUD_~1/x.txt') is True
    assert has_win_path_alias('/static/uploads/CON') is True
    assert has_win_path_alias('/static/uploads/com1.txt') is True
    assert has_win_path_alias('/static/uploads/a/normal_file.pdf') is False


def test_private_upload_path_case_and_alias_variants_are_denied(app):
    static_root = app.static_folder
    target_dir = os.path.join(static_root, 'uploads', 'cloud_drive', SID)
    filename = f'secret_{uuid.uuid4().hex}.txt'
    target = os.path.join(target_dir, filename)
    os.makedirs(target_dir, exist_ok=True)
    with open(target, 'wb') as f:
        f.write(b'private-content')
    client = app.test_client()
    try:
        canonical = f'/static/uploads/cloud_drive/{SID}/{filename}'
        # 匿名（未登录学生）本就不能读；大小写/别名变体也不得绕过
        assert client.get(canonical).status_code == 403
        variants = [
            f'/static/UPLOADS/cloud_drive/{SID}/{filename}',
            f'/static/uploads/CLOUD_DRIVE/{SID}/{filename}',
            f'/static/uploads/cloud_drive/{SID}/{filename.upper()}',
            f'/static/uploads/cloud_drive/{SID}/{filename}.',
            f'/static/uploads/cloud_drive/{SID}/{filename} ',
        ]
        for path in variants:
            resp = client.get(path)
            assert resp.status_code == 403, (path, resp.status_code, len(resp.data))
        # 私有路径即使被拒，缓存头也必须是 no-store/private（防代理缓存回放）
        resp = client.get(f'/static/UPLOADS/cloud_drive/{SID}/{filename}')
        cache_control = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cache_control and 'private' in cache_control, cache_control
        # 公共静态资源不受影响
        assert client.get('/static/favicon.ico').status_code == 200
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
