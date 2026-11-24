# -*- coding: utf-8 -*-
"""学生端课堂资源按上课教师范围过滤（2026-10-26 / 2026-11-04 收紧）。

覆盖：
- 班级有教师上课时，只显示该教师任教学科范围内的自有 + 授权共享资源；
- 其他教师未授权资源、其他学科共享资源不显示；授课教师范围内资源
  即使 show_in_student=False 也可用（课堂展示即授权）；
- 未分类的授权/自有资源保留；
- 无教师上课时只保留公开/内置允许公开资源（不再回退全局资源列表）；
- SSR /study 与 SPA /api/resources 口径一致。
"""
import uuid
from datetime import datetime

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (
    Class, ClassroomSession, Resource, Student, Subject, Teacher,
    TeachingSession, resource_share, teacher_class, teacher_subject,
)

CSRF = 'scope-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_student_resources_follow_active_teacher_scope(app):
    sfx = uuid.uuid4().hex[:8]
    c1_name = f'__scope_c1_{sfx}'
    c2_name = f'__scope_c2_{sfx}'
    s1_name = f'__scope_s1_{sfx}'
    s2_name = f'__scope_s2_{sfx}'
    a_name = f'__scope_a_{sfx}'
    b_name = f'__scope_b_{sfx}'
    c_name = f'__scope_c_{sfx}'
    stu1_num = f'__scope_stu1_{sfx}'
    stu2_num = f'__scope_stu2_{sfx}'
    titles = {
        'a_own': f'__scope_a_own_{sfx}',
        'b_own': f'__scope_b_own_{sfx}',
        'b_shared': f'__scope_b_shared_{sfx}',
        'b_other_subject': f'__scope_b_other_{sfx}',
        'admin_shared': f'__scope_admin_shared_{sfx}',
        'admin_unshared': f'__scope_admin_unshared_{sfx}',
        'a_unclassified': f'__scope_a_unclassified_{sfx}',
        'a_hidden': f'__scope_a_hidden_{sfx}',
        'c_own': f'__scope_c_own_{sfx}',
    }
    ids = {}
    try:
        cache.delete('study:resources:student')
        cache.delete('api:resources:list:student')
        with app.app_context():
            c1 = Class(name=c1_name)
            c2 = Class(name=c2_name)
            s1 = Subject(name=s1_name, sort_order=930)
            s2 = Subject(name=s2_name, sort_order=931)
            a = Teacher(username=a_name, display_name='范围教师A')
            a.set_password('pass123456')
            b = Teacher(username=b_name, display_name='范围教师B')
            b.set_password('pass123456')
            c = Teacher(username=c_name, display_name='范围教师C')
            c.set_password('pass123456')
            a.subjects = [s1]
            b.subjects = [s1]
            c.subjects = [s2]
            a.classes = [c1]
            b.classes = [c1]
            stu1 = Student(name='范围学生1', student_number=stu1_num,
                           student_class=c1_name, class_id=None,
                           has_changed_password=True)
            stu1.set_password('pass123456')
            stu2 = Student(name='范围学生2', student_number=stu2_num,
                           student_class=c2_name, class_id=None,
                           has_changed_password=True)
            stu2.set_password('pass123456')
            db.session.add_all([c1, c2, s1, s2, a, b, c, stu1, stu2])
            db.session.flush()
            stu1.class_id = c1.id
            stu2.class_id = c2.id

            def mk(title, subject_id, creator, student_visible=True):
                r = Resource(
                    title=title, url=f'https://example.com/{title}',
                    subject_id=subject_id, show_in_student=student_visible,
                    show_in_classroom=True, quiz_mode='none',
                    creator_type='teacher' if creator else 'admin',
                    creator_teacher_id=creator.id if creator else None,
                    creator_name=creator.display_name if creator else '管理员')
                db.session.add(r)
                return r

            ra = mk(titles['a_own'], s1.id, a)
            rb = mk(titles['b_own'], s1.id, b)
            rb_shared = mk(titles['b_shared'], s1.id, b)
            rb_other = mk(titles['b_other_subject'], s2.id, c)
            admin_shared = mk(titles['admin_shared'], s1.id, None)
            admin_unshared = mk(titles['admin_unshared'], s1.id, None)
            ra_unclassified = mk(titles['a_unclassified'], None, a)
            ra_hidden = mk(titles['a_hidden'], s1.id, a, False)
            rc = mk(titles['c_own'], s2.id, c)
            db.session.flush()
            rb_shared.shared_teachers.append(a)
            rb_other.shared_teachers.append(a)
            admin_shared.shared_teachers.append(a)

            # A 在 1 班上课；C 的 2 班没有上课记录
            session = TeachingSession(
                resource_id=ra.id, teacher_id=a.id, teacher_name=a.display_name,
                class_id=c1.id, status='active', end_time=None)
            db.session.add(session)
            db.session.add(ClassroomSession(class_id=c1.id, is_active=True))
            db.session.add(ClassroomSession(class_id=c2.id, is_active=True))
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
            ids = {
                'a': a.id, 'b': b.id, 'c': c.id,
                'stu1': stu1.id, 'stu2': stu2.id,
                'res': {k: v.id for k, v in {
                    'a_own': ra, 'b_own': rb, 'b_shared': rb_shared,
                    'b_other_subject': rb_other, 'admin_shared': admin_shared,
                    'admin_unshared': admin_unshared,
                    'a_unclassified': ra_unclassified, 'a_hidden': ra_hidden,
                    'c_own': rc,
                }.items()},
                'c1': c1.id, 'c2': c2.id, 's1': s1.id, 's2': s2.id,
            }

        student1 = _client(app, student_id=ids['stu1'])
        page = student1.get('/study')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert titles['a_own'] in text
        assert titles['b_shared'] in text
        assert titles['admin_shared'] in text
        assert titles['a_unclassified'] in text
        assert titles['b_own'] not in text
        assert titles['b_other_subject'] not in text
        assert titles['admin_unshared'] not in text
        # 课堂跟随教师：教师自有资源即使未勾选「学生端可见」也可在课堂使用
        assert titles['a_hidden'] in text
        assert titles['c_own'] not in text
        assert s2_name not in text

        api = student1.get('/api/resources').get_json()
        assert api['success']
        api_ids = {item['id'] for item in api['data']}
        # 上课班级学生范围 = 上课教师（本人/共享）+ 管理员授权命中（年级×学科，
        # 含内置资源默认的「不限」通配行）+ 旧 is_public（无授权记录时）
        with app.app_context():
            from app.models import resource_audience
            public_ids = {r.id for r in Resource.query.filter_by(
                is_public=True, show_in_student=True).all()}
            wildcard_ids = {row.resource_id for row in db.session.execute(
                resource_audience.select().where(
                    resource_audience.c.grade.is_(None),
                    resource_audience.c.subject_id.is_(None))).fetchall()}
            visible_extra_ids = {r.id for r in Resource.query.filter(
                Resource.id.in_(public_ids | wildcard_ids),
                Resource.show_in_student.is_(True)).all()}
        assert api_ids == {
            ids['res']['a_own'], ids['res']['b_shared'],
            ids['res']['admin_shared'], ids['res']['a_unclassified'],
            ids['res']['a_hidden'],
        } | visible_extra_ids
        # 直链也不能绕过当前上课教师范围
        assert student1.get(
            f'/study/lesson/{ids["res"]["a_own"]}').status_code == 200
        assert student1.get(
            f'/study/lesson/{ids["res"]["b_own"]}').status_code == 404
        assert student1.get(
            '/study/link?resource_id=%s&url=https://example.com/x' %
            ids['res']['b_own']).status_code == 403

        # 2 班没有教师上课：仅显示公开/内置资源，不再回退全局列表
        student2 = _client(app, student_id=ids['stu2'])
        page2 = student2.get('/study')
        assert page2.status_code == 200
        text2 = page2.get_data(as_text=True)
        assert titles['b_own'] not in text2
        assert titles['c_own'] not in text2
        assert titles['a_own'] not in text2
        assert titles['a_hidden'] not in text2
        # 无授课教师时教师资源直链同样不可访问
        assert student2.get(
            f'/study/lesson/{ids["res"]["b_own"]}').status_code == 404

        # 同班两位教师同时上课：取两位教师资源范围的并集
        with app.app_context():
            db.session.add(TeachingSession(
                resource_id=ids['res']['b_own'], teacher_id=ids['b'],
                teacher_name='范围教师B', class_id=ids['c1'],
                status='active', end_time=None))
            db.session.commit()
        text_multi = student1.get('/study').get_data(as_text=True)
        assert titles['a_own'] in text_multi
        assert titles['b_own'] in text_multi
        assert titles['b_shared'] in text_multi
        assert titles['b_other_subject'] not in text_multi

        # 只结束教学记录、课堂仍开放：回退该班任课教师范围
        with app.app_context():
            db.session.query(TeachingSession).filter_by(
                class_id=ids['c1']).update(
                    {TeachingSession.end_time: datetime.now(),
                     TeachingSession.status: 'ended'},
                    synchronize_session=False)
            db.session.commit()
            cache.delete('study:resources:student')
        text3 = student1.get('/study').get_data(as_text=True)
        assert titles['a_own'] in text3
        assert titles['b_own'] in text3
        assert titles['b_shared'] in text3
        assert titles['b_other_subject'] not in text3
        assert student1.get(
            f'/study/lesson/{ids["res"]["b_own"]}').status_code == 200

        # 班级无任课教师时教师范围失效：仅保留公开/内置资源
        with app.app_context():
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.class_id == ids['c1']))
            db.session.commit()
            cache.delete('study:resources:student')
        text4 = student1.get('/study').get_data(as_text=True)
        assert titles['b_own'] not in text4
        assert titles['c_own'] not in text4
        assert titles['a_own'] not in text4
        assert student1.get(
            f'/study/lesson/{ids["res"]["b_own"]}').status_code == 404
    finally:
        with app.app_context():
            # 按唯一前缀清理，避免依赖 ids（异常时 ids 可能为空）
            class_ids = [c.id for c in Class.query.filter(
                Class.name.in_([c1_name, c2_name])).all()]
            teacher_ids = [t.id for t in Teacher.query.filter(
                Teacher.username.in_([a_name, b_name, c_name])).all()]
            resource_ids = [r.id for r in Resource.query.filter(
                Resource.title.like(f'__scope_%_{sfx}')).all()]
            if class_ids:
                TeachingSession.query.filter(
                    TeachingSession.class_id.in_(class_ids)).delete(
                        synchronize_session=False)
                ClassroomSession.query.filter(
                    ClassroomSession.class_id.in_(class_ids)).delete(
                        synchronize_session=False)
            if resource_ids:
                db.session.execute(resource_share.delete().where(
                    resource_share.c.resource_id.in_(resource_ids)))
                Resource.query.filter(Resource.id.in_(resource_ids)).delete(
                    synchronize_session=False)
            Student.query.filter(Student.student_number.in_(
                [stu1_num, stu2_num])).delete(synchronize_session=False)
            if teacher_ids:
                db.session.execute(teacher_subject.delete().where(
                    teacher_subject.c.teacher_id.in_(teacher_ids)))
                db.session.execute(teacher_class.delete().where(
                    teacher_class.c.teacher_id.in_(teacher_ids)))
                Teacher.query.filter(Teacher.id.in_(teacher_ids)).delete(
                    synchronize_session=False)
            if class_ids:
                Class.query.filter(Class.id.in_(class_ids)).delete(
                    synchronize_session=False)
                from app.blueprints.auth import invalidate_active_class_cache
                invalidate_active_class_cache()
            Subject.query.filter(Subject.name.in_([s1_name, s2_name])).delete(
                synchronize_session=False)
            db.session.commit()
            cache.delete('study:resources:student')
            cache.delete('api:resources:list:student')
