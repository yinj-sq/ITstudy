# -*- coding: utf-8 -*-
"""教师学科、资源归属/共享与只读登录回归（2026-10-22）。"""
import pathlib
import shutil
import uuid

from werkzeug.security import generate_password_hash

from app import create_app
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import (Resource, Subject, Teacher, SystemConfig, Class,
                        resource_share, teacher_subject, teacher_class)
from app.utils import password_fingerprint

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 't'


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None):
    data = dict(data or {})
    data['csrf_token'] = CSRF
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def test_teacher_subjects_and_resource_permissions():
    suffix = uuid.uuid4().hex[:8]
    names = {
        's1': f'__tp_sub1_{suffix}', 's2': f'__tp_sub2_{suffix}',
        't1': f'__tp_t1_{suffix}', 't2': f'__tp_t2_{suffix}',
    }
    titles = {k: f'__tp_res_{k}_{suffix}' for k in ('own1', 'own2', 'admin', 'admin_shared')}
    dirs = {k: f'__tp_dir_{k}_{suffix}' for k in titles}
    ids = {}
    old_code = None
    app = create_app()
    try:
        with app.app_context():
            old_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
            s1 = Subject(name=names['s1'], sort_order=901)
            s2 = Subject(name=names['s2'], sort_order=902)
            t1 = Teacher(username=names['t1'], display_name='权限教师一')
            t1.set_password('pass123456')
            t1.subjects = [s1]
            t2 = Teacher(username=names['t2'], display_name='权限教师二')
            t2.set_password('pass123456')
            t2.subjects = [s1, s2]
            db.session.add_all([s1, s2, t1, t2])
            db.session.flush()
            resources = []
            for key, creator in (('own1', t1), ('own2', t2), ('admin', None),
                                 ('admin_shared', None)):
                d = dirs[key]
                folder = UPLOADS / d
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'index.html').write_text('<html>x</html>', encoding='utf-8')
                r = Resource(
                    title=titles[key], url=f'/static/uploads/{d}/index.html',
                    subject_id=s1.id, show_in_student=True,
                    show_in_classroom=True, quiz_mode='none',
                    creator_type='teacher' if creator else 'admin',
                    creator_teacher_id=creator.id if creator else None,
                    creator_name=creator.display_name if creator else '管理员')
                resources.append(r)
            db.session.add_all(resources)
            db.session.flush()
            # t1 的资源共享给 t2；管理员未共享资源不授权
            resources[0].shared_teachers = [t2]
            resources[3].shared_teachers = [t2]
            db.session.commit()
            ids = {'s1': s1.id, 's2': s2.id, 't1': t1.id, 't2': t2.id}
            for key, r in zip(titles, resources):
                ids[key] = r.id
            code = 'ReadOnly-123'
            code_hash = generate_password_hash(code, method='pbkdf2:sha256')
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, code_hash)
            db.session.commit()
            code_fp = password_fingerprint(code_hash)

        # 编辑模式：只看到自己的资源
        t1_edit = _client(app, is_teacher=True, teacher_id=ids['t1'],
                          teacher_name='权限教师一', teacher_mode='edit')
        html = t1_edit.get('/teacher/resource-library').get_data(as_text=True)
        assert titles['own1'] in html
        assert titles['own2'] not in html and titles['admin'] not in html
        assert t1_edit.get(f'/teacher/resource-library/edit/{ids["own2"]}').status_code in (403, 404)

        # 只读模式：自己的 + 被共享的；管理员未授权资源不可见
        t2_ro = _client(app, is_teacher=True, teacher_id=ids['t2'],
                        teacher_name='权限教师二', teacher_mode='readonly',
                        readonly_code_fp=code_fp)
        html = t2_ro.get('/teacher/resource-library').get_data(as_text=True)
        assert titles['own2'] in html and titles['own1'] in html
        assert titles['admin_shared'] in html and titles['admin'] not in html
        classroom = t2_ro.get('/study?mode=classroom').get_data(as_text=True)
        assert titles['own2'] in classroom and titles['own1'] in classroom
        assert titles['admin_shared'] in classroom and titles['admin'] not in classroom
        assert t2_ro.get(f'/study/lesson/{ids["own1"]}').status_code == 200
        assert t2_ro.get(f'/study/lesson/{ids["admin"]}').status_code == 404

        # 编辑模式下共享资源仍不可编辑
        t2_edit = _client(app, is_teacher=True, teacher_id=ids['t2'],
                          teacher_name='权限教师二', teacher_mode='edit')
        assert t2_edit.get(f'/study/lesson/{ids["own1"]}').status_code == 404
        assert _post(t2_edit, f'/admin/resources/delete/{ids["own1"]}').status_code == 403
        with app.app_context():
            assert db.session.get(Resource, ids['own1']) is not None

        # 只读写操作被全局守卫拦截，资源不消失
        resp = _post(t2_ro, f'/admin/resources/delete/{ids["own2"]}')
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(Resource, ids['own2']) is not None

        # 只读模式不能查看学生隐私/教师管理页
        privacy = t2_ro.get('/teacher/works', follow_redirects=False)
        assert privacy.status_code == 302
        assert 'mode=classroom' in privacy.headers.get('Location', '')

        # 创建者共享/取消共享
        resp = _post(t1_edit, f'/teacher/resource-library/{ids["own1"]}/share',
                     {'teacher_ids': [str(ids['t2'])]})
        assert resp.status_code == 302
        with app.app_context():
            shared = db.session.execute(
                resource_share.select().where(
                    resource_share.c.resource_id == ids['own1'])).fetchall()
            assert {row.teacher_id for row in shared} == {ids['t2']}

        # 管理员创建的资源由管理员授权后，只读教师才可见/可用
        admin = _client(app, is_admin=True, admin_name='管理员')
        edit_html = admin.get(f'/admin/resources/edit/{ids["admin"]}').get_data(as_text=True)
        assert '共享给其他教师' in edit_html
        resp = _post(admin, f'/teacher/resource-library/{ids["admin"]}/share',
                     {'teacher_ids': [str(ids['t2'])]})
        assert resp.status_code == 302
        classroom_after = t2_ro.get('/study?mode=classroom').get_data(as_text=True)
        assert titles['admin'] in classroom_after

        # 只读登录：需访问码；编辑登录：需密码
        anon = _client(app)
        bad = _post(anon, '/teacher/login', {'username': names['t2'],
                                             'mode': 'readonly',
                                             'readonly_code': 'wrong'})
        assert bad.status_code == 200
        with anon.session_transaction() as s:
            assert not s.get('is_teacher')
        good = _post(anon, '/teacher/login', {'username': names['t2'],
                                              'mode': 'readonly',
                                              'readonly_code': code})
        assert good.status_code == 302 and 'mode=classroom' in good.headers['Location']
        with anon.session_transaction() as s:
            assert s.get('teacher_mode') == 'readonly'
        anon.post('/teacher/logout', headers={'X-CSRFToken': CSRF})
        edit = _post(anon, '/teacher/login', {'username': names['t2'],
                                              'password': 'pass123456'})
        assert edit.status_code == 302 and (
            'teacher/dashboard' in edit.headers['Location']
            or 'resource-library' in edit.headers['Location'])
        with anon.session_transaction() as s:
            assert s.get('teacher_mode') == 'edit'
    finally:
        with app.app_context():
            # 先删多对多关联，再删资源，避免外键约束阻塞
            db.session.execute(resource_share.delete())
            Resource.query.filter(Resource.id.in_(
                [ids.get(k) for k in titles if ids.get(k)])).delete(
                synchronize_session=False)
            db.session.execute(teacher_subject.delete())
            Teacher.query.filter(Teacher.username.in_(
                [names['t1'], names['t2']])).delete(synchronize_session=False)
            Subject.query.filter(Subject.name.in_(
                [names['s1'], names['s2']])).delete(synchronize_session=False)
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, old_code)
            db.session.commit()
        for d in dirs.values():
            shutil.rmtree(UPLOADS / d, ignore_errors=True)


def test_admin_teacher_create_requires_subjects():
    suffix = uuid.uuid4().hex[:8]
    app = create_app()
    subj = None
    username = f'__tp_create_{suffix}'
    class_name = f'__tp_create_class_{suffix}'
    try:
        with app.app_context():
            subj = Subject(name=f'__tp_create_sub_{suffix}', sort_order=905)
            cls = Class(name=class_name, description='教师分配测试')
            db.session.add_all([subj, cls])
            db.session.commit()
            sid, cid = subj.id, cls.id
        admin = _client(app, is_admin=True, admin_name='管理员')
        assert admin.get('/admin/teacher_account').status_code == 200
        resp = _post(admin, '/admin/teacher_account', {
            'action': 'create', 'username': username, 'password': 'pass123456',
            'display_name': '学科教师', 'subject_ids': [str(sid)],
            'grade': '高一', 'class_ids': [str(cid)]})
        assert resp.status_code == 302
        with app.app_context():
            teacher = Teacher.query.filter_by(username=username).first()
            assert teacher is not None
            assert [s.id for s in teacher.subjects] == [sid]
            assert teacher.grade == '高一'
            assert [c.id for c in teacher.classes] == [cid]
    finally:
        with app.app_context():
            db.session.execute(teacher_subject.delete())
            db.session.execute(teacher_class.delete())
            Teacher.query.filter_by(username=username).delete(synchronize_session=False)
            if subj:
                Subject.query.filter_by(id=subj.id).delete(synchronize_session=False)
            Class.query.filter_by(name=class_name).delete(synchronize_session=False)
            db.session.commit()


def test_deleting_teacher_reassigns_owned_resources_and_cleans_links():
    suffix = uuid.uuid4().hex[:8]
    subj_name = f'__tp_del_sub_{suffix}'
    username = f'__tp_del_teacher_{suffix}'
    title = f'__tp_del_res_{suffix}'
    app = create_app()
    try:
        with app.app_context():
            subj = Subject(name=subj_name, sort_order=906)
            teacher = Teacher(username=username, display_name='待删教师')
            teacher.set_password('pass123456')
            teacher.subjects = [subj]
            db.session.add_all([subj, teacher])
            db.session.flush()
            teacher_id, subject_id = teacher.id, subj.id
            resource = Resource(title=title, url='https://example.com/x',
                                subject_id=subject_id, creator_type='teacher',
                                creator_teacher_id=teacher_id, creator_name='待删教师')
            db.session.add(resource)
            db.session.commit()
            resource_id, teacher_id = resource.id, teacher.id
        admin = _client(app, is_admin=True, admin_name='管理员')
        resp = _post(admin, '/admin/teacher_account', {
            'action': 'delete', 'teacher_id': str(teacher_id)})
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(Teacher, teacher_id) is None
            res = db.session.get(Resource, resource_id)
            assert res is not None and res.creator_type == 'admin'
            assert res.creator_teacher_id is None
            assert db.session.execute(
                teacher_subject.select().where(
                    teacher_subject.c.teacher_id == teacher_id)).first() is None
    finally:
        with app.app_context():
            Resource.query.filter_by(title=title).delete(synchronize_session=False)
            db.session.execute(teacher_subject.delete())
            Teacher.query.filter_by(username=username).delete(synchronize_session=False)
            Subject.query.filter_by(name=subj_name).delete(synchronize_session=False)
            db.session.commit()
