# -*- coding: utf-8 -*-
"""文档预览扩展名与 PPTX 状态提示回归（2026-10-22）。"""
import pathlib
import shutil
import uuid

from flask import render_template

from app import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'


def test_preview_uses_real_file_extension_when_name_lacks_it():
    suffix = uuid.uuid4().hex[:8]
    dir_name = f'__preview_ext_{suffix}'
    folder = UPLOADS / dir_name
    folder.mkdir(parents=True)
    try:
        app = create_app()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['is_admin'] = True
            sess['admin_name'] = '预览测试'
        for ext in ('docx', 'pdf', 'md'):
            name = f'第一章导学_{ext}'
            path = folder / f'guide.{ext}'
            path.write_bytes(b'x')
            resp = client.get('/study/preview', query_string={
                'file': f'/static/uploads/{dir_name}/{path.name}',
                'name': name,
            })
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)
            assert f'var ext = "{ext}"' in html
            assert name + '.' + ext in html
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_preview_template_tolerates_missing_ext_variable():
    """所有预览入口都必须能渲染：只有资源预览传 ext，其余从文件名兜底。

    回归背景：2026-10-22 模板改为读取 ext，但个人网盘/小组网盘/作业/活动
    等入口未传该变量，Undefined 进 tojson 导致整页 500（E2E 实测）。
    """
    app = create_app()
    with app.test_request_context('/'):
        html = render_template('document_preview.html', filename='指南.pdf',
                               file_url='/x', download_url='/y')
        assert 'var ext = "pdf"' in html
        html = render_template('document_preview.html', filename='无扩展名',
                               file_url='/x', download_url='/y')
        assert 'var ext = ""' in html
        html = render_template('document_preview.html', filename='a.docx',
                               file_url='/x', download_url='/y', ext='docx')
        assert 'var ext = "docx"' in html


def test_pptx_imported_status_is_cleared():
    src = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    assert "textContent = '解析完成'" not in src
    block = src[src.index("msg.action === 'pptxImported'"):]
    block = block[:block.index("msg.action === 'data'")]
    assert 'hide($(\'pptistStatus\'))' in block
