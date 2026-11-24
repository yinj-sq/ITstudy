# -*- coding: utf-8 -*-
"""教师上传资源与创建者标记回归（2026-10-22）。"""
import io
import pathlib
import shutil
import uuid

from app import create_app
from app.extensions import db
from app.models import Log, Resource, Subject, Teacher, teacher_subject
from app.services.resource_access import resource_access_level

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 't'


def test_teacher_upload_marks_creator_and_uses_teacher_namespace():
    suffix = uuid.uuid4().hex[:8]
    subj_name = f'__tu_sub_{suffix}'
    username = f'__tu_teacher_{suffix}'
    title = f'教师上传资源_{suffix}'
    dir_name = None
    app = create_app()
    try:
        with app.app_context():
            subj = Subject(name=subj_name, sort_order=910)
            teacher = Teacher(username=username, display_name='上传教师')
            teacher.set_password('pass123456')
            teacher.subjects = [subj]
            db.session.add_all([subj, teacher])
            db.session.commit()
            sid, tid = subj.id, teacher.id
            dir_name = f't{tid}_' + title
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['is_teacher'] = True
            sess['teacher_id'] = tid
            sess['teacher_name'] = '上传教师'
            sess['teacher_mode'] = 'edit'
            sess['csrf_token'] = CSRF
        upload_id = 'tu_' + suffix
        resp = client.post('/admin/resources/chunk_upload', data={
            'csrf_token': CSRF,
            'chunk': (io.BytesIO(b'<html>teacher</html>'), 'index.html'),
            'chunk_index': '0', 'total_chunks': '1',
            'filename': 'index.html', 'upload_id': upload_id,
            'title': title, 'subfolder': '', 'quiz_mode': 'none',
        }, content_type='multipart/form-data', headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success']
        payload = {
            'title': title, 'directory': title, 'subject_id': sid,
            'homepage': 'index.html', 'homework': [], 'inject_files': [],
            'permissions': {'index.html': {'show': True, 'download': True}},
            'delete_files': [], 'show_in_student': True,
            'show_in_classroom': True, 'quiz_mode': 'none',
        }
        resp = client.post('/admin/resources/save_with_settings', json=payload,
                           headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        assert resp.get_json()['success']
        with app.app_context():
            res = Resource.query.filter_by(title=title).first()
            assert res is not None
            assert res.creator_type == 'teacher' and res.creator_teacher_id == tid
            assert res.subject_id == sid
            assert res.url.startswith(f'/static/uploads/t{tid}_')
            assert resource_access_level(res, tid) == 'owner'
            assert resource_access_level(res, tid + 1) == 'none'
    finally:
        with app.app_context():
            Log.query.filter(Log.detail.contains(title)).delete(
                synchronize_session=False)
            Resource.query.filter_by(title=title).delete(synchronize_session=False)
            db.session.execute(teacher_subject.delete())
            Teacher.query.filter_by(username=username).delete(synchronize_session=False)
            Subject.query.filter_by(name=subj_name).delete(synchronize_session=False)
            db.session.commit()
        if dir_name:
            shutil.rmtree(UPLOADS / dir_name, ignore_errors=True)
