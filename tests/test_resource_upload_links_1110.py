# -*- coding: utf-8 -*-
"""上传完成状态与课堂 HTML 相对链接回归（2026-11-10）。"""
import io
import json
import pathlib
import shutil
import subprocess
import uuid
from urllib.parse import urljoin

import pytest

from app import create_app
from app.extensions import db
from app.models import Resource, Student, SystemConfig

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSRF = 'upload-links-1110'


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture
def upload_client(app, tmp_path, monkeypatch):
    from app.blueprints import resources
    monkeypatch.setattr(resources, '_BASE', str(tmp_path))
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(is_admin=True, csrf_token=CSRF)
    return client, tmp_path


def _chunk(client, *, index=0, total=1, data=b'', **fields):
    return client.post('/admin/resources/chunk_upload', data={
        'chunk': (io.BytesIO(data), 'blob'),
        'chunk_index': str(index), 'total_chunks': str(total),
        'filename': '课程/第一页.html', 'title': '上传回归1110',
        'upload_id': 'upload-1110', 'subfolder': '章节 包',
        **fields,
    }, headers={'X-CSRFToken': CSRF})


def test_chunk_status_returns_completed_path_with_subfolder(upload_client):
    client, root = upload_client
    params = {'filename': '课程/第一页.html', 'title': '上传回归1110',
              'upload_id': 'upload-1110', 'subfolder': '章节 包', 'total_chunks': 2}
    first = _chunk(client, index=0, total=2, data=b'<html>')
    assert first.status_code == 200
    assert first.json['is_complete'] is False
    status = client.get('/admin/resources/chunk_status', query_string=params)
    assert status.json['received'] == [0]
    assert status.json['merged'] is False
    last = _chunk(client, index=1, total=2, data=b'</html>')
    assert last.status_code == 200 and last.json['is_complete'] is True
    rel = '章节_包/课程/第一页.html'
    assert last.json['filename'] == rel
    status = client.get('/admin/resources/chunk_status', query_string=params)
    assert status.json['merged'] is True
    assert status.json['filename'] == rel
    assert (root / 'static/uploads/上传回归1110' / rel).read_bytes() == b'<html></html>'


def test_empty_file_is_really_uploaded(upload_client):
    client, root = upload_client
    response = _chunk(client, filename='empty.txt', subfolder='')
    assert response.status_code == 200 and response.json['is_complete'] is True
    file = root / 'static/uploads/上传回归1110/empty.txt'
    assert file.is_file() and file.stat().st_size == 0


_JS_DRIVER = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
class FormData {
  constructor() { this.fields = {}; }
  append(key, value) { this.fields[key] = value; }
}
class XHR {
  constructor() { this.upload = {}; }
  open(method, url) { this.method = method; this.url = url; }
  send(data) {
    calls.push({method: this.method, fields: data?.fields || {}});
    const step = input.steps.shift();
    if (!step || step.method !== this.method) throw new Error('意外的请求顺序');
    this.status = step.status || 200;
    this.responseText = JSON.stringify(step.body);
    queueMicrotask(() => this.onload());
  }
}
const ctx = vm.createContext({
  FormData, XMLHttpRequest: XHR, window: {}, console,
  CHUNK_SIZE: 2, currentXHR: null, uploadCancelled: false,
  MAX_CONCURRENT_UPLOADS: 3,
  uploadPathOf: file => file.webkitRelativePath || file.name,
  setTimeout: fn => queueMicrotask(fn),
});
vm.runInContext(input.source, ctx);
const file = {name: 'index.html', size: input.size, lastModified: 1110,
              slice: () => 'chunk'};
ctx.uploadFileInChunks(file, '上传回归', '子目录', 'none').then(
  value => console.log(JSON.stringify({value, calls, remaining: input.steps.length})),
  error => console.log(JSON.stringify({error: error.message, calls, remaining: input.steps.length}))
);
"""


def _run_upload_js(steps, size=2):
    node = shutil.which('node')
    if not node:
        pytest.skip('前端协议回归需要 Node.js')
    source = (ROOT / 'templates/admin_resources_upload.html').read_text(encoding='utf-8')
    source = source[source.index('  function makeUploadId'):source.index('  // 并发控制上传')]
    result = subprocess.run([node, '-e', _JS_DRIVER], input=json.dumps({
        'source': source, 'steps': steps, 'size': size,
    }), text=True, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _status(received=None, **fields):
    return {'method': 'GET', 'body': {
        'success': True, 'received': received or [], 'merged': False, **fields}}


def _received(**fields):
    return {'method': 'POST', 'body': {'success': True, 'is_complete': False, **fields}}


def test_frontend_recovers_missing_prefix_instead_of_resolving_undefined():
    result = _run_upload_js([
        _status([0]), _received(), _received(),
        _status([2]), _received(),
        _received(is_complete=True, filename='子目录/index.html'),
    ], size=6)
    assert result.get('value') == '子目录/index.html', result
    assert [c['fields']['chunk_index'] for c in result['calls']
            if c['method'] == 'POST'] == ['1', '2', '0', '1']
    assert result['remaining'] == 0


def test_frontend_incomplete_merge_has_bounded_retry_and_clear_error():
    result = _run_upload_js([_status(), _received()] * 3)
    assert '尚未合并完成' in result.get('error', ''), result
    assert 'match' not in result['error'] and result['remaining'] == 0
    assert 'value' not in result


@pytest.mark.parametrize('response', [
    _received(is_complete=True), _received(is_complete=True, filename=None),
    _received(is_complete=True, filename=42),
])
def test_frontend_rejects_missing_completed_filename(response):
    result = _run_upload_js([_status(), response])
    assert '未返回已完成文件的路径' in result.get('error', ''), result


def test_frontend_resume_uses_server_path_and_uploads_empty_files():
    merged = _run_upload_js([
        _status(merged=True, filename='服务器子目录/index.html')])
    assert merged.get('value') == '服务器子目录/index.html'
    assert len(merged['calls']) == 1
    empty = _run_upload_js([
        _status(), _received(is_complete=True, filename='empty.html')], size=0)
    assert empty.get('value') == 'empty.html'
    assert empty['calls'][1]['fields']['total_chunks'] == '1'


@pytest.fixture
def course(app, tmp_path, monkeypatch):
    from app.blueprints import resources
    monkeypatch.setattr(resources, '_BASE', str(tmp_path))
    monkeypatch.setattr(app, 'static_folder', str(tmp_path / 'static'))
    folder = tmp_path / 'static/uploads/course1110'
    (folder / '课件/子目录').mkdir(parents=True)
    files = {
        '课件/index.html': '<html><head></head><body><a href="子目录/下一页.html">下一页</a></body></html>',
        '课件/子目录/下一页.html': '<a href="../index.html#top">返回</a>',
        '课件/theme.css': 'body { color: navy; }',
        '课件/secret.html': '教师答案',
        '课件/doc.pdf': '%PDF-1.4\n',
    }
    for name, content in files.items():
        (folder / name).write_text(content, encoding='utf-8')
    tree = [{'id': 'section', 'title': '课程', 'children': [], 'items': [
        {'id': 'entry', 'kind': 'link', 'title': '网页',
         'src': '/static/uploads/course1110/课件/index.html',
         'visible': {'teacher': True, 'student': True}},
        {'id': 'secret', 'kind': 'link', 'title': '隐藏网页',
         'src': '/static/uploads/course1110/课件/secret.html',
         'visible': {'teacher': True, 'student': False}},
        {'id': 'pdf', 'kind': 'doc', 'title': 'PDF', 'src': '课件/doc.pdf',
         'visible': {'teacher': True, 'student': True}},
    ]}]
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        student = Student(name=f'__links_{suffix}', student_number=f'__links_{suffix}',
                          has_changed_password=True)
        resource = Resource(title=f'__links_{suffix}',
                            url='/static/uploads/course1110/课件/index.html',
                            is_public=True, show_in_student=True, show_in_classroom=True,
                            lesson_tree=json.dumps(tree, ensure_ascii=False),
                            file_permissions=json.dumps({
                                '课件/index.html': {'show': False},
                                '课件/secret.html': {'show': False},
                                '课件/doc.pdf': {'show': False},
                            }, ensure_ascii=False))
        db.session.add_all([student, resource])
        db.session.commit()
        sid, rid = student.id, resource.id
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(student_id=sid, csrf_token=CSRF)
    yield client, rid, folder
    with app.app_context():
        Resource.query.filter_by(id=rid).delete(synchronize_session=False)
        Student.query.filter_by(id=sid).delete(synchronize_session=False)
        db.session.commit()


def test_lesson_html_preserves_nested_links_assets_and_fragment(course):
    client, rid, folder = course
    first = client.get(f'/study/lesson/{rid}/item/entry/file')
    assert first.status_code == 302
    entry = first.headers['Location']
    assert '/content/' in entry and entry.endswith('index.html')
    response = client.get(entry)
    assert response.status_code == 200
    assert response.data == (folder / '课件/index.html').read_bytes()
    assert 'no-store' in response.headers['Cache-Control']
    response.close()
    second_url = urljoin(entry, '子目录/下一页.html')
    second = client.get(second_url)
    assert second.status_code == 200
    second.close()
    back = client.get(urljoin(second_url, '../index.html#top'))
    assert back.status_code == 200
    back.close()
    css = client.get(urljoin(entry, 'theme.css'))
    assert css.status_code == 200 and css.mimetype == 'text/css'
    css.close()
    # 无编排的默认树也不得把站内绝对路径再拼一次 uploads 前缀。
    js = (ROOT / 'static/js/study_lesson.js').read_text(encoding='utf-8')
    assert 'return isLocalUploadSrc(src) ? src :' in js


def test_lesson_navigation_keeps_hidden_and_path_boundaries(course):
    client, rid, _ = course
    root = f'/study/lesson/{rid}/item/entry/content/'
    assert client.get(root + '课件/secret.html').status_code == 403
    assert client.get(f'/study/lesson/{rid}/item/secret/file').status_code == 404
    assert client.get(root.replace('/entry/', '/unknown/') + '课件/index.html').status_code == 404
    for bad in ('../outside.txt', '课件/../secret.html', '课件/index.html.',
                '课件/index.html::$DATA', '课件//secret.html'):
        assert client.get(root + bad).status_code in (403, 404), bad
    assert client.get('/static/uploads/course1110/课件/index.html').status_code == 403
    pdf = client.get(f'/study/lesson/{rid}/item/pdf/file')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    pdf.close()


def test_lesson_routes_honor_disabled_anonymous_courseware(app, course):
    _, rid, _ = course
    with app.app_context():
        previous = SystemConfig.get('courseware_public_enabled')
        SystemConfig.set('courseware_public_enabled', 'false')
        db.session.commit()
    try:
        anon = app.test_client()
        for path in (f'/study/lesson/{rid}/item/entry/file',
                     f'/study/lesson/{rid}/item/entry/content/课件/index.html'):
            assert anon.get(path).status_code == 404
    finally:
        with app.app_context():
            if previous is None:
                SystemConfig.query.filter_by(key='courseware_public_enabled').delete()
                SystemConfig._invalidate_cache()
            else:
                SystemConfig.set('courseware_public_enabled', previous)
            db.session.commit()
