# -*- coding: utf-8 -*-
"""活动改名/删除与课堂章节树同步回归（2026-10-23）。"""
import json
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import LearningActivity, Resource

CSRF = 't'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_activity_edit_and_delete_sync_lesson_tree(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__tree_activity_{sfx}'
    new_title = f'__tree_activity_new_{sfx}'
    res_title = f'__tree_resource_{sfx}'
    rid = aid = None
    try:
        with app.app_context():
            res = Resource(title=res_title, show_in_student=True,
                           show_in_classroom=True)
            db.session.add(res)
            db.session.flush()
            act = LearningActivity(resource_id=res.id, title=title,
                                   require_upload=True, is_active=True)
            db.session.add(act)
            db.session.flush()
            res.lesson_tree = json.dumps([{
                'id': 'ch1', 'title': '第一课堂', 'type': 'section',
                'children': [], 'items': [
                    {'id': 'act1', 'title': title, 'kind': 'activity',
                     'src': '', 'activity_id': act.id,
                     'visible': {'teacher': True, 'student': True}},
                    {'id': 'doc1', 'title': '讲义', 'kind': 'doc',
                     'src': 'guide.pdf', 'doc_category': 'guide',
                     'visible': {'teacher': True, 'student': True}},
                ]}], ensure_ascii=False)
            db.session.commit()
            rid, aid = res.id, act.id

        admin = _client(app, is_admin=True, admin_name='管理员')
        resp = admin.post(f'/admin/activities/{aid}/edit', data={
            'csrf_token': CSRF, 'title': new_title, 'description': '更新说明',
            'require_upload': '1', 'sort_order': '0', 'is_active': '1',
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code in (301, 302)
        with app.app_context():
            tree = json.loads(db.session.get(Resource, rid).lesson_tree)
            items = tree[0]['items']
            activity_item = next(i for i in items if i.get('activity_id') == aid)
            assert activity_item['title'] == new_title
            assert any(i.get('id') == 'doc1' for i in items)

        resp = admin.post(f'/admin/activities/{aid}/delete',
                          data={'csrf_token': CSRF},
                          headers={'X-CSRFToken': CSRF})
        assert resp.status_code in (301, 302)
        with app.app_context():
            assert db.session.get(LearningActivity, aid) is None
            tree = json.loads(db.session.get(Resource, rid).lesson_tree)
            items = tree[0]['items']
            assert not any(i.get('activity_id') == aid for i in items)
            assert any(i.get('id') == 'doc1' for i in items)
            aid = None
    finally:
        with app.app_context():
            if aid:
                act = db.session.get(LearningActivity, aid)
                if act:
                    db.session.delete(act)
            if rid:
                res = db.session.get(Resource, rid)
                if res:
                    db.session.delete(res)
            db.session.commit()
