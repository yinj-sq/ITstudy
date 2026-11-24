# -*- coding: utf-8 -*-
"""资源上传禁止类型回归（2026-10-21）。

问题：文件夹中混入 exe/bat 等文件时，旧实现把分块全部传完（进度 99%）
才在最后合并阶段拒绝，前端又只显示 "HTTP 400"，用户不知道是哪个文件。
修复：上传页开始前列出具体文件并阻止上传；服务端在第一个分块就拒绝。
"""
import io
import pathlib
import uuid

from app import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
TITLE = '__上传类型校验1021__'
CSRF = 't'


def test_chunk_upload_rejects_disallowed_type_on_first_chunk():
    app = create_app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['admin_name'] = '上传校验'
        sess['csrf_token'] = CSRF

    upload_id = 'bad_' + uuid.uuid4().hex[:12]
    data = {
        'chunk': (io.BytesIO(b'not a real executable'), 'bad.exe'),
        'chunk_index': '0',
        'total_chunks': '3',
        'filename': '课件子目录/bad.exe',
        'upload_id': upload_id,
        'title': TITLE,
        'csrf_token': CSRF,
    }
    resp = client.post('/admin/resources/chunk_upload', data=data,
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['success'] is False
    assert 'bad.exe' in body['msg']
    assert '不允许上传' in body['msg']
    # 首个分块即拒绝，不应落下任何临时分块目录
    assert not (ROOT / 'static' / 'chunks' / upload_id).exists()


def test_upload_page_prevalidates_folder_before_starting():
    src = (ROOT / 'templates' / 'admin_resources_upload.html').read_text(
        encoding='utf-8')
    assert 'REJECT_EXTS' in src
    assert '所选文件/文件夹中包含不允许上传的可执行/脚本文件' in src
    # 校验必须发生在上传状态置位之前
    assert src.index('所选文件/文件夹中包含不允许上传') < src.index('isUploading = true')


def test_edit_resource_page_prevalidates_folder():
    src = (ROOT / 'templates' / 'edit_resource.html').read_text(encoding='utf-8')
    assert 'REJECT_EXTS' in src
    assert '所选文件/文件夹中包含不允许上传的可执行/脚本文件' in src
    # 校验必须在逐文件 fetch 之前
    assert src.index('所选文件/文件夹中包含不允许上传') < src.index('await fetch(')
