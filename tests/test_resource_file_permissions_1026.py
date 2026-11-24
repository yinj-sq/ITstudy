# -*- coding: utf-8 -*-
"""资源文件属性保存与 .bak 备份过滤回归（2026-10-26）。"""
import json
import pathlib
import shutil
import uuid

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import Log, Resource

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'perm-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def test_edit_resource_permissions_save_and_backup_hidden(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__perm_res_{sfx}'
    dir_name = f'__perm_dir_{sfx}'
    rid = None
    try:
        target = UPLOADS / dir_name
        (target / 'sub').mkdir(parents=True, exist_ok=True)
        (target / 'sub' / 'a.html').write_text('<html>a</html>', encoding='utf-8')
        (target / 'sub' / 'b.html').write_text('<html>b</html>', encoding='utf-8')
        (target / 'sub' / 'a.html.bak').write_text('<html>backup</html>', encoding='utf-8')
        with app.app_context():
            res = Resource(title=title,
                           url=f'/static/uploads/{dir_name}/sub/a.html',
                           show_in_student=True, show_in_classroom=True,
                           quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            rid = res.id
        client = app.test_client()
        with client.session_transaction() as s:
            s.update(is_admin=True, admin_name='管理员', csrf_token=CSRF)
        page = client.get(f'/admin/resources/edit/{rid}').get_data(as_text=True)
        assert 'sub/a.html.bak' not in page
        assert 'sub/a.html' in page and 'sub/b.html' in page
        resp = client.post(f'/admin/resources/edit/{rid}', data={
            'csrf_token': CSRF,
            'title': title,
            'subject_id': '',
            'show_in_student': '1',
            'show_in_classroom': '1',
            'quiz_mode': 'none',
            'homepage': 'sub/a.html',
            'perm_show_sub/a.html': '1',
            'perm_download_sub/a.html': '1',
            'perm_show_sub/b.html': '1',
            # b 的下载故意不勾选
        }, follow_redirects=False)
        assert resp.status_code in (302, 303)
        with app.app_context():
            saved = db.session.get(Resource, rid)
            perms = json.loads(saved.file_permissions or '{}')
            assert perms.get('sub/a.html') == {'show': True, 'download': True}
            assert perms.get('sub/b.html') == {'show': True, 'download': False}
        page2 = client.get(f'/admin/resources/edit/{rid}').get_data(as_text=True)
        assert 'sub/a.html.bak' not in page2
        # 重新勾选状态应回显（b 展示勾选、下载未勾选）
        assert 'name="perm_show_sub/b.html" value="1" class="show-cb" checked' in page2
        assert 'name="perm_download_sub/b.html" value="1" class="download-cb" ' in page2
        study = client.get(f'/study?q={title}').get_data(as_text=True)
        assert title in study
        assert 'sub/a.html.bak' not in study
    finally:
        with app.app_context():
            if rid is not None:
                Log.query.filter(Log.detail.contains(title)).delete(
                    synchronize_session=False)
                Resource.query.filter_by(id=rid).delete(synchronize_session=False)
                db.session.commit()
            cache.delete(f'study:files:{dir_name}')
        shutil.rmtree(UPLOADS / dir_name, ignore_errors=True)


def test_edit_resource_allow_related_files_toggle(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__related_res_{sfx}'
    dir_name = f'__related_dir_{sfx}'
    rid = None
    try:
        target = UPLOADS / dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'index.html').write_text('<html>home</html>', encoding='utf-8')
        with app.app_context():
            res = Resource(
                title=title,
                url=f'/static/uploads/{dir_name}/index.html',
                show_in_student=True, show_in_classroom=True,
                quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            rid = res.id
        client = app.test_client()
        with client.session_transaction() as s:
            s.update(is_admin=True, admin_name='管理员', csrf_token=CSRF)
        page = client.get(f'/admin/resources/edit/{rid}').get_data(as_text=True)
        assert 'name="allow_related_files"' in page
        data = {
            'csrf_token': CSRF,
            'title': title,
            'subject_id': '',
            'show_in_student': '1',
            'show_in_classroom': '1',
            'allow_related_files': '1',
            'quiz_mode': 'none',
            'homepage': 'index.html',
            'perm_show_index.html': '1',
            'perm_download_index.html': '1',
        }
        assert client.post(f'/admin/resources/edit/{rid}', data=data,
                           follow_redirects=False).status_code in (302, 303)
        with app.app_context():
            assert db.session.get(Resource, rid).allow_related_files is True
        data.pop('allow_related_files')
        assert client.post(f'/admin/resources/edit/{rid}', data=data,
                           follow_redirects=False).status_code in (302, 303)
        with app.app_context():
            assert db.session.get(Resource, rid).allow_related_files is False
    finally:
        with app.app_context():
            if rid is not None:
                Log.query.filter(Log.detail.contains(title)).delete(
                    synchronize_session=False)
                Resource.query.filter_by(id=rid).delete(
                    synchronize_session=False)
                db.session.commit()
            cache.delete(f'study:files:{dir_name}')
            cache.delete('courseware:dir_map')
        shutil.rmtree(UPLOADS / dir_name, ignore_errors=True)


def test_upload_snapshot_is_metadata_only_and_collectors_are_lazy(app):
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__snap_dir_{sfx}'
    target = UPLOADS / dir_name
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'quiz.html').write_text(
            '<html><script>ITSTUDY_QUIZ_COLLECTOR</script></html>',
            encoding='utf-8')
        (target / 'plain.html').write_text('<html>plain</html>',
                                           encoding='utf-8')
        (target / 'app.js').write_text('const x=1;', encoding='utf-8')
        from app.blueprints.resources import (_upload_dir_collectors,
                                              _upload_dir_snapshot)
        with app.app_context():
            cache.delete(f'study:files:{dir_name}')
            snap = _upload_dir_snapshot(dir_name)
            assert 'collectors' not in snap
            assert {f['name'] for f in snap['files']} == {
                'quiz.html', 'plain.html', 'app.js'}
            assert snap.get('version')
            collectors = _upload_dir_collectors(dir_name, snap)
            assert collectors == {'quiz.html': True, 'plain.html': False}
    finally:
        with app.app_context():
            cache.delete(f'study:files:{dir_name}')
            cache.delete(f'study:collectors:{dir_name}:legacy')
        shutil.rmtree(target, ignore_errors=True)


def test_admin_resource_files_lazy_load(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__admin_lazy_{sfx}'
    dir_name = f'__admin_lazy_dir_{sfx}'
    rid = None
    try:
        target = UPLOADS / dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'a.html').write_text('<html>a</html>', encoding='utf-8')
        with app.app_context():
            res = Resource(
                title=title,
                url=f'/static/uploads/{dir_name}/a.html',
                show_in_student=True, show_in_classroom=True,
                quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            rid = res.id
        client = app.test_client()
        with client.session_transaction() as s:
            s.update(is_admin=True, admin_name='管理员', csrf_token=CSRF)
        page = client.get('/admin/resources').get_data(as_text=True)
        assert f'/admin/resources/{rid}/files' in page
        assert 'a.html' not in page
        files = client.get(f'/admin/resources/{rid}/files')
        assert files.status_code == 200
        text = files.get_data(as_text=True)
        assert 'data-file-count="1"' in text and 'a.html' in text
    finally:
        with app.app_context():
            if rid is not None:
                Log.query.filter(Log.detail.contains(title)).delete(
                    synchronize_session=False)
                Resource.query.filter_by(id=rid).delete(
                    synchronize_session=False)
                db.session.commit()
            cache.delete(f'study:files:{dir_name}')
        shutil.rmtree(UPLOADS / dir_name, ignore_errors=True)
