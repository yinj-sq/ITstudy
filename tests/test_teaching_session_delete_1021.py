# -*- coding: utf-8 -*-
"""教学记录删除权限与分页回跳回归（2026-10-21）。"""
import uuid
from datetime import datetime

from app import create_app
from app.extensions import db
from app.models import Resource, Teacher, TeachingSession

CSRF = 't'


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _delete(client, session_id, next_url=None):
    data = {'csrf_token': CSRF}
    if next_url:
        data['next'] = next_url
    return client.post(f'/teaching-sessions/{session_id}/delete', data=data,
                       headers={'X-CSRFToken': CSRF})


def test_teaching_session_delete_permissions_and_redirect():
    suffix = uuid.uuid4().hex[:8]
    title = f'__教学记录删除测试_{suffix}'
    user1 = f'__tdel_t1_{suffix}'
    user2 = f'__tdel_t2_{suffix}'
    res_id = t1_id = t2_id = None
    ids = {}

    app = create_app()
    with app.app_context():
        res = Resource(title=title, url=f'/static/uploads/{title}/index.html',
                       show_in_student=True, show_in_classroom=True, quiz_mode='none')
        t1 = Teacher(username=user1, display_name='删除测试教师一')
        t1.set_password('x')
        t2 = Teacher(username=user2, display_name='删除测试教师二')
        t2.set_password('x')
        db.session.add_all([res, t1, t2])
        db.session.flush()
        res_id, t1_id, t2_id = res.id, t1.id, t2.id
        now = datetime.now()
        own = TeachingSession(resource_id=res_id, teacher_id=t1_id,
                              teacher_name='删除测试教师一', start_time=now,
                              end_time=now, duration_minutes=1, status='ended')
        own2 = TeachingSession(resource_id=res_id, teacher_id=t1_id,
                               teacher_name='删除测试教师一', start_time=now,
                               end_time=now, duration_minutes=1, status='ended')
        other = TeachingSession(resource_id=res_id, teacher_id=t2_id,
                                teacher_name='删除测试教师二', start_time=now,
                                status='active')
        admin_rec = TeachingSession(resource_id=res_id, teacher_id=None,
                                    teacher_name='管理员', start_time=now,
                                    status='ended')
        db.session.add_all([own, own2, other, admin_rec])
        db.session.commit()
        ids = {'own': own.id, 'own2': own2.id,
               'other': other.id, 'admin': admin_rec.id}

    try:
        admin = _client(app, is_admin=True, admin_name='删除测试管理员')
        page = admin.get('/admin/teaching-sessions').get_data(as_text=True)
        assert '删除教学记录' in page and 'name="csrf_token"' in page

        # 管理员可删除任意记录，并回到来源分页
        resp = _delete(admin, ids['own'], '/admin/teaching-sessions?page=1')
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/admin/teaching-sessions?page=1')
        with app.app_context():
            assert db.session.get(TeachingSession, ids['own']) is None

        # 教师可删除自己的记录
        teacher = _client(app, is_teacher=True, teacher_id=t1_id,
                          teacher_name='删除测试教师一')
        resp = _delete(teacher, ids['own2'])
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(TeachingSession, ids['own2']) is None

        # 但他人的记录（含管理员代课记录）一律 403
        resp = _delete(teacher, ids['other'])
        assert resp.status_code == 403
        resp = _delete(teacher, ids['admin'])
        assert resp.status_code == 403
        with app.app_context():
            assert db.session.get(TeachingSession, ids['other']) is not None
            assert db.session.get(TeachingSession, ids['admin']) is not None
    finally:
        with app.app_context():
            TeachingSession.query.filter_by(resource_id=res_id).delete(
                synchronize_session=False)
            res = db.session.get(Resource, res_id)
            if res:
                db.session.delete(res)
            Teacher.query.filter(Teacher.id.in_([t1_id, t2_id])).delete(
                synchronize_session=False)
            db.session.commit()
