# -*- coding: utf-8 -*-
"""课堂编排器资源根目录 API 回归（2026-10-22）。"""
import json
import pathlib
import shutil
import uuid

from app import create_app
from app.blueprints.resources import (
    _DOC_CATEGORIES, _lesson_doc_previewable, _lesson_file_kind,
)
from app.extensions import db
from app.models import Resource

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['admin_name'] = '编排目录测试'
        sess['csrf_token'] = 't'
    return client


def test_lesson_files_api_lists_root_and_hidden_files():
    suffix = uuid.uuid4().hex[:8]
    dir_name = f'__le_pick_{suffix}'
    title = f'编排目录测试_{suffix}'
    folder = UPLOADS / dir_name
    folder.mkdir(parents=True)
    (folder / 'index.html').write_text('<html>home</html>', encoding='utf-8')
    (folder / 'slides.pptx').write_bytes(b'pptx')
    (folder / 'archive.zip').write_bytes(b'zip')
    (folder / '.hidden.txt').write_text('hidden', encoding='utf-8')
    (folder / 'slide1.pptist.json').write_text('{}', encoding='utf-8')
    (folder / 'mindmap-test.json').write_text('{}', encoding='utf-8')
    (folder / 'video').mkdir()
    (folder / 'video' / 'lesson.mp4').write_bytes(b'mp4')
    (folder / 'docs').mkdir()
    (folder / 'docs' / 'answer.pdf').write_bytes(b'pdf')

    app = create_app()
    ids = []
    try:
        with app.app_context():
            res = Resource(
                title=title, url=f'/static/uploads/{dir_name}/index.html',
                show_in_student=True, show_in_classroom=True, quiz_mode='none',
                file_permissions=json.dumps({'docs/answer.pdf': {'show': False}}),
            )
            external = Resource(title=title + '_外链', url='https://example.com/x')
            db.session.add_all([res, external])
            db.session.commit()
            ids = [res.id, external.id]

        client = _admin_client(app)
        resp = client.get(f'/admin/resources/{ids[0]}/lesson_files')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] and data['supported']
        assert data['root']['dir'] == dir_name
        names = [e['name'] for e in data['entries']]
        assert 'index.html' in names and 'slides.pptx' in names
        assert 'video' in names and 'docs' in names and 'archive.zip' in names
        assert '.hidden.txt' not in names
        assert 'slide1.pptist.json' not in names
        assert 'mindmap-test.json' not in names
        by_name = {e['name']: e for e in data['entries']}
        assert by_name['slides.pptx']['kind'] == 'pptx'
        assert by_name['index.html']['kind'] == 'link'
        assert by_name['archive.zip']['kind'] == 'other'
        assert by_name['video']['is_dir'] is True

        resp = client.get(f'/admin/resources/{ids[0]}/lesson_files?path=docs')
        assert resp.status_code == 200
        docs = resp.get_json()
        answer = next(e for e in docs['entries'] if e['name'] == 'answer.pdf')
        assert answer['can_show'] is False
        assert answer['kind'] == 'doc' and answer['previewable'] is True
        assert docs['breadcrumb'][-1]['name'] == 'docs'

        resp = client.get(f'/admin/resources/{ids[0]}/lesson_files?path=video')
        video = next(e for e in resp.get_json()['entries']
                     if e['name'] == 'lesson.mp4')
        assert video['kind'] == 'video'

        assert client.get(
            f'/admin/resources/{ids[0]}/lesson_files?path=../').status_code == 400

        ext = client.get(f'/admin/resources/{ids[1]}/lesson_files').get_json()
        assert ext['success'] is True and ext['supported'] is False
        assert '外链' in ext['msg']
    finally:
        with app.app_context():
            Resource.query.filter(Resource.id.in_(ids)).delete(
                synchronize_session=False)
            db.session.commit()
        shutil.rmtree(folder, ignore_errors=True)


def test_lesson_file_type_and_doc_categories_expanded():
    assert _lesson_file_kind('mp4') == 'video'
    assert _lesson_file_kind('flac') == 'video'
    assert _lesson_file_kind('tsv') == 'doc'
    assert _lesson_file_kind('markdown') == 'doc'
    assert _lesson_file_kind('tiff') == 'doc'
    assert _lesson_doc_previewable('tsv') is True
    assert _lesson_doc_previewable('markdown') is True
    assert _lesson_doc_previewable('xml') is False
    assert _lesson_doc_previewable('tiff') is False
    for cat in ('activity_sheet', 'guide', 'design', 'handout',
                'exercise', 'answer', 'material', 'other'):
        assert cat in _DOC_CATEGORIES


def test_editor_frontend_uses_root_picker():
    js = (ROOT / 'static' / 'js' / 'lesson_editor.js').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'css' / 'lesson_editor.css').read_text(encoding='utf-8')
    for marker in ('/lesson_files?path=', '从资源根目录选择文件', '定位根目录',
                   'le-picker-overlay', "['doc', '电子文档']"):
        assert marker in js, marker
    assert '.le-picker-overlay' in css and '.le-picker-row' in css


def test_edit_page_starts_with_default_tree():
    """没有自定义树时，编排器必须以默认编排为起点，避免新增章节后主页消失。"""
    suffix = uuid.uuid4().hex[:8]
    dir_name = f'__le_default_{suffix}'
    title = f'默认编排测试_{suffix}'
    folder = UPLOADS / dir_name
    folder.mkdir(parents=True)
    (folder / 'index.html').write_text('<html>home</html>', encoding='utf-8')
    (folder / 'slides.pptx').write_bytes(b'pptx')
    app = create_app()
    rid = None
    try:
        with app.app_context():
            res = Resource(title=title, url=f'/static/uploads/{dir_name}/index.html',
                           show_in_student=True, show_in_classroom=True, quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            rid = res.id
        client = _admin_client(app)
        html = client.get(f'/admin/resources/edit/{rid}').get_data(as_text=True)
        assert '默认编排（可编辑）' in html
        # tojson 会把中文转成 \uXXXX；用文件名验证默认树确有内容
        assert 'index.html' in html and 'slides.pptx' in html
    finally:
        with app.app_context():
            Resource.query.filter_by(id=rid).delete(synchronize_session=False)
            db.session.commit()
        shutil.rmtree(folder, ignore_errors=True)
