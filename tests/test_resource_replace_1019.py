# -*- coding: utf-8 -*-
"""已上传资源文件新增/替换回归（2026-10-21）。"""
import io
import pathlib

from app import create_app
from app.extensions import db
from app.models import Log, Resource

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
TITLE = '资源替换回归'
DIR = UPLOADS / '资源替换回归'
CSRF = 't'


def _post_file(client, path, name, content, extra=None):
    data = dict(extra or {})
    data['csrf_token'] = CSRF
    data['files'] = (io.BytesIO(content), name)
    return client.post(path, data=data,
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': CSRF})


def test_resource_upload_replace_and_folder_add():
    app = create_app()
    with app.app_context():
        Resource.query.filter_by(title=TITLE).delete(synchronize_session=False)
        Log.query.filter(Log.detail.like(f'%{TITLE}%')).delete(
            synchronize_session=False)
        db.session.commit()
    DIR.mkdir(parents=True, exist_ok=True)
    old = DIR / 'note.txt'
    old.write_bytes(b'old')
    (DIR / 'note.txt.gz').write_bytes(b'old-gz')
    with app.app_context():
        res = Resource(title=TITLE, url=f'/static/uploads/{DIR.name}/note.txt',
                       show_in_student=True, show_in_classroom=True,
                       quiz_mode='none')
        db.session.add(res)
        db.session.commit()
        rid = res.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['csrf_token'] = CSRF
    try:
        # 同名覆盖
        resp = _post_file(client, f'/admin/resources/{rid}/upload_files',
                          'note.txt', b'new', {'replace': '1'})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        data = resp.get_json()
        assert data['success'] and data['replaced'] == ['note.txt']
        assert old.read_bytes() == b'new'
        assert not (DIR / 'note.txt.gz').exists()

        # 文件夹上传（相对路径保留）
        resp = _post_file(client, f'/admin/resources/{rid}/upload_files',
                          'sub/new.txt', b'nested', {'replace': '1'})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        assert (DIR / 'sub' / 'new.txt').read_bytes() == b'nested'

        # 不覆盖时自动避让
        resp = _post_file(client, f'/admin/resources/{rid}/upload_files',
                          'note.txt', b'second', {'replace': '0'})
        assert resp.status_code == 200
        assert (DIR / 'note (1).txt').read_bytes() == b'second'
    finally:
        with app.app_context():
            Resource.query.filter_by(id=rid).delete(synchronize_session=False)
            Log.query.filter(Log.detail.like(f'%{TITLE}%')).delete(
                synchronize_session=False)
            db.session.commit()
        import shutil
        shutil.rmtree(DIR, ignore_errors=True)
