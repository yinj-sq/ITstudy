# -*- coding: utf-8 -*-
"""学生作品删除权限与状态回归（2026-11-04）。

需求：创建活动的教师（资源创建者）或管理员可删除活动中的学生作品；
删除后学生端活动页恢复为“未提交”状态（显示上传表单、不再显示“我的作品”）。
共享（只读）教师不可删除；学生不能调用教师端删除接口。
"""
import pathlib
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, LearningActivity, Log, Resource, Student,
                        StudentWork, Teacher, WorkEvaluation, resource_share,
                        teacher_class)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'work-delete-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None):
    data = dict(data or {})
    data.setdefault('csrf_token', CSRF)
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def test_work_delete_permissions_and_student_state(app):
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__work_del_{sfx}'
    target = UPLOADS / 'student_works' / dir_name
    ids = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
        with app.app_context():
            cls = Class(name=f'__wd_cls_{sfx}')
            owner = Teacher(username=f'__wd_own_{sfx}', display_name='作品教师')
            owner.set_password('pass123456')
            shared = Teacher(username=f'__wd_sha_{sfx}', display_name='共享教师')
            shared.set_password('pass123456')
            owner.classes.append(cls)
            stu = Student(name='作品学生', student_number=f'__wd_s_{sfx}',
                          student_class=cls.name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, owner, shared, stu])
            db.session.flush()
            stu.class_id = cls.id
            res = Resource(title=f'__wd_res_{sfx}', url='',
                           show_in_student=True, show_in_classroom=True,
                           is_public=True,
                           creator_type='teacher', creator_teacher_id=owner.id,
                           creator_name=owner.display_name)
            db.session.add(res)
            db.session.flush()
            db.session.execute(resource_share.insert().values(
                resource_id=res.id, teacher_id=shared.id))
            act = LearningActivity(resource_id=res.id,
                                   title=f'__wd_act_{sfx}',
                                   require_upload=True, is_active=True)
            db.session.add(act)
            db.session.commit()
            ids.update(cls=cls.id, owner=owner.id, shared=shared.id,
                       stu=stu.id, res=res.id, act=act.id)

        def make_work():
            with app.app_context():
                rel = f'student_works/{dir_name}/answer.txt'
                work = StudentWork(activity_id=ids['act'],
                                   student_id=ids['stu'],
                                   status='submitted',
                                   original_filename='answer.txt',
                                   file_path=rel, file_size=8)
                db.session.add(work)
                db.session.flush()
                db.session.add(WorkEvaluation(
                    work_id=work.id, score=90, grade='A',
                    comment='作品评价'))
                db.session.commit()
                return work.id, rel

        def work_exists(work_id):
            with app.app_context():
                return db.session.get(StudentWork, work_id) is not None

        wid, rel = make_work()
        (target / 'answer.txt').write_text('作品内容', encoding='utf-8')

        owner_client = _client(app, is_teacher=True,
                               teacher_id=ids['owner'],
                               teacher_name='作品教师', teacher_mode='edit')
        shared_client = _client(app, is_teacher=True,
                                teacher_id=ids['shared'],
                                teacher_name='共享教师',
                                teacher_mode='edit')
        admin = _client(app, is_admin=True, admin_name='管理员')
        student = _client(app, student_id=ids['stu'], student_name='作品学生')

        # 创建者/管理员作品列表有删除入口；共享只读教师无
        page = owner_client.get(f'/teacher/works/activity/{ids["act"]}')
        assert page.status_code == 200
        assert '删除' in page.get_data(as_text=True)
        page = admin.get(f'/admin/works/activity/{ids["act"]}')
        assert page.status_code == 200
        assert '删除' in page.get_data(as_text=True)
        # 学生端此时能看到“我的作品”
        page = student.get(f'/study/activity/{ids["act"]}')
        assert '我的作品' in page.get_data(as_text=True)

        # 共享教师不可删除
        resp = _post(shared_client, f'/teacher/works/{wid}/delete')
        assert resp.status_code == 403
        assert work_exists(wid)

        # 创建者删除：作品与评价删除、文件清理
        resp = _post(owner_client, f'/teacher/works/{wid}/delete')
        assert resp.status_code in (302, 303)
        assert not work_exists(wid)
        with app.app_context():
            assert WorkEvaluation.query.filter_by(work_id=wid).count() == 0
            log = Log.query.filter_by(action='删除学生作品').order_by(
                Log.id.desc()).first()
            assert log is not None
        assert not (target / 'answer.txt').exists()

        # 学生端恢复为“未提交”状态：有上传表单，无“我的作品”
        page = student.get(f'/study/activity/{ids["act"]}').get_data(
            as_text=True)
        assert '上传作品' in page
        assert '我的作品' not in page

        # 管理员同样可删除
        wid2, rel2 = make_work()
        (target / 'answer.txt').write_text('作品内容2', encoding='utf-8')
        resp = _post(admin, f'/admin/works/{wid2}/delete')
        assert resp.status_code in (302, 303)
        assert not work_exists(wid2)
        assert not (target / 'answer.txt').exists()

        # 学生无法调用教师端删除接口
        wid3, _ = make_work()
        resp = _post(student, f'/teacher/works/{wid3}/delete')
        assert resp.status_code in (302, 303)
        assert work_exists(wid3)
    finally:
        with app.app_context():
            if ids.get('act'):
                wids = [w.id for w in StudentWork.query.filter_by(
                    activity_id=ids['act']).all()]
                if wids:
                    WorkEvaluation.query.filter(
                        WorkEvaluation.work_id.in_(wids)).delete(
                            synchronize_session=False)
                    StudentWork.query.filter(
                        StudentWork.id.in_(wids)).delete(
                            synchronize_session=False)
                LearningActivity.query.filter_by(
                    id=ids['act']).delete(synchronize_session=False)
            if ids.get('res'):
                db.session.execute(resource_share.delete().where(
                    resource_share.c.resource_id == ids['res']))
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            if ids.get('stu'):
                Student.query.filter_by(id=ids['stu']).delete(
                    synchronize_session=False)
            for key in ('owner', 'shared'):
                if ids.get(key):
                    db.session.execute(teacher_class.delete().where(
                        teacher_class.c.teacher_id == ids[key]))
                    Teacher.query.filter_by(id=ids[key]).delete(
                        synchronize_session=False)
            if ids.get('cls'):
                Class.query.filter_by(id=ids['cls']).delete(
                    synchronize_session=False)
            db.session.commit()
        import shutil
        shutil.rmtree(target, ignore_errors=True)
