# -*- coding: utf-8 -*-
"""教师编辑模式活动管理与撤销注入回归（2026-11-02）。

修复点：
- 教师自有资源未勾选「教师端可见」时，仍可在资源库进入活动管理并创建活动；
- 资源库/活动管理页提供教师活动入口，不再只有管理员资源页有入口；
- 教师创建者可撤销自己资源的采集器注入，共享教师不可；
- 活动创建/编辑/删除限资源创建者（管理员除外），避免只读共享教师越权。
"""
import pathlib
import shutil
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (LearningActivity, Resource, Teacher,
                        resource_share)
from app.utils import inject_quiz_collector, is_html_injected

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'teacher-activity-injection-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None, **kwargs):
    data = dict(data or {})
    data.setdefault('csrf_token', CSRF)
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF}, **kwargs)


def _suffix():
    return uuid.uuid4().hex[:8]


def test_teacher_own_resource_activity_and_revert_injection(app):
    sfx = _suffix()
    dir_name = f'__teacher_act_{sfx}'
    target = UPLOADS / dir_name
    ids = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
        page = target / 'index.html'
        original = '<html><body>课堂活动单</body></html>'
        page.write_text(original, encoding='utf-8')

        with app.app_context():
            owner = Teacher(username=f'__ta_owner_{sfx}', display_name='活动资源教师')
            owner.set_password('pass123456')
            other = Teacher(username=f'__ta_other_{sfx}', display_name='其他教师')
            other.set_password('pass123456')
            db.session.add_all([owner, other])
            db.session.flush()
            res = Resource(
                title=f'__ta_res_{sfx}',
                url=f'/static/uploads/{dir_name}/index.html',
                show_in_student=True,
                show_in_classroom=False,
                creator_type='teacher',
                creator_teacher_id=owner.id,
                creator_name=owner.display_name,
                quiz_mode='inject',
            )
            db.session.add(res)
            db.session.commit()
            ids = {'owner': owner.id, 'other': other.id, 'res': res.id}
            inject_quiz_collector(str(page), res.id, 'index.html')
            res.injected = True
            res.quiz_inject_state = 'verified'
            db.session.commit()
            assert is_html_injected(str(page))

        owner_client = _client(
            app, is_teacher=True, teacher_id=ids['owner'],
            teacher_name='活动资源教师', teacher_mode='edit')

        # 资源库与活动管理都应有入口；未开放到课堂也不影响活动创建
        lib = owner_client.get('/teacher/resource-library').get_data(as_text=True)
        assert f'/teacher/resources/{ids["res"]}/activities' in lib
        assert '撤销注入' in lib
        manage = owner_client.get('/teacher/resources').get_data(as_text=True)
        assert f'__ta_res_{sfx}' in manage
        activities_page = owner_client.get(
            f'/teacher/resources/{ids["res"]}/activities')
        assert activities_page.status_code == 200
        assert '新增活动' in activities_page.get_data(as_text=True)

        # 创建 → 编辑 → 删除
        resp = _post(owner_client, f'/teacher/resources/{ids["res"]}/activities/new',
                     {'title': f'__ta_act_{sfx}', 'is_active': '1'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            act = LearningActivity.query.filter_by(resource_id=ids['res']).one()
            ids['act'] = act.id
            assert act.title == f'__ta_act_{sfx}'

        # 未开放到课堂的自有资源，作品云盘/作品详情也应可进入，避免
        # “能建活动、看不到学生作品”的断层
        works_page = owner_client.get('/teacher/works')
        assert works_page.status_code == 200
        assert f'__ta_res_{sfx}' in works_page.get_data(as_text=True)
        works_detail = owner_client.get(
            f'/teacher/works/activity/{ids["act"]}')
        assert works_detail.status_code == 200

        resp = _post(owner_client, f'/teacher/activities/{ids["act"]}/edit',
                     {'title': f'__ta_act_edit_{sfx}', 'is_active': '1'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert db.session.get(LearningActivity, ids['act']).title == \
                f'__ta_act_edit_{sfx}'

        # 编辑页应展示撤销注入；教师端点可还原
        edit_html = owner_client.get(
            f'/teacher/resource-library/edit/{ids["res"]}').get_data(as_text=True)
        assert '撤销注入' in edit_html
        revert = owner_client.post(
            f'/teacher/resource-library/{ids["res"]}/revert-injection',
            headers={'X-CSRFToken': CSRF})
        assert revert.status_code == 200
        assert revert.get_json()['success'] is True
        assert page.read_text(encoding='utf-8') == original
        with app.app_context():
            assert db.session.get(Resource, ids['res']).injected is False

        # 共享教师（编辑模式）不能创建/编辑/删除活动，也不能撤销注入
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            other = db.session.get(Teacher, ids['other'])
            res.shared_teachers.append(other)
            db.session.commit()
        other_client = _client(
            app, is_teacher=True, teacher_id=ids['other'],
            teacher_name='其他教师', teacher_mode='edit')
        before = None
        with app.app_context():
            before = LearningActivity.query.filter_by(
                resource_id=ids['res']).count()
        deny_create = _post(
            other_client, f'/teacher/resources/{ids["res"]}/activities/new',
            {'title': f'__ta_forbidden_{sfx}'})
        assert deny_create.status_code in (302, 303)
        with app.app_context():
            assert LearningActivity.query.filter_by(
                resource_id=ids['res']).count() == before

        # 只读共享教师：资源库不出现活动/编辑入口，直接 POST 也不能创建
        ro_client = _client(
            app, is_teacher=True, teacher_id=ids['other'],
            teacher_name='其他教师', teacher_mode='readonly')
        ro_lib = ro_client.get('/teacher/resource-library').get_data(as_text=True)
        assert f'/teacher/resources/{ids["res"]}/activities' not in ro_lib
        ro_create = _post(
            ro_client, f'/teacher/resources/{ids["res"]}/activities/new',
            {'title': f'__ta_readonly_forbidden_{sfx}'})
        assert ro_create.status_code in (302, 303)
        with app.app_context():
            assert LearningActivity.query.filter_by(
                resource_id=ids['res']).count() == before

        # 重新注入后，共享教师撤销请求应 403；创建者仍可撤销（管理员路径同口径）
        with app.app_context():
            inject_quiz_collector(str(page), ids['res'], 'index.html')
            db.session.get(Resource, ids['res']).injected = True
            db.session.commit()
        deny_revert = other_client.post(
            f'/teacher/resource-library/{ids["res"]}/revert-injection',
            headers={'X-CSRFToken': CSRF})
        assert deny_revert.status_code == 403
        assert is_html_injected(str(page))
        admin_client = _client(app, is_admin=True, admin_name='管理员')
        admin_activities_page = admin_client.get(
            f'/admin/resources/{ids["res"]}/activities')
        assert admin_activities_page.status_code == 200
        assert '新增活动' in admin_activities_page.get_data(as_text=True)
        admin_revert = admin_client.post(
            f'/admin/resources/{ids["res"]}/revert-injection',
            headers={'X-CSRFToken': CSRF})
        assert admin_revert.status_code == 200
        assert admin_revert.get_json()['success'] is True
        assert not is_html_injected(str(page))

        # 删除活动（创建者）
        resp = _post(owner_client, f'/teacher/activities/{ids["act"]}/delete')
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert db.session.get(LearningActivity, ids['act']) is None
    finally:
        with app.app_context():
            if ids.get('act'):
                LearningActivity.query.filter_by(id=ids['act']).delete(
                    synchronize_session=False)
            if ids.get('res'):
                db.session.execute(resource_share.delete().where(
                    resource_share.c.resource_id == ids['res']))
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            if ids.get('owner'):
                Teacher.query.filter_by(id=ids['owner']).delete(
                    synchronize_session=False)
            if ids.get('other'):
                Teacher.query.filter_by(id=ids['other']).delete(
                    synchronize_session=False)
            db.session.commit()
        shutil.rmtree(target, ignore_errors=True)
