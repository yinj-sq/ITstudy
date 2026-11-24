# -*- coding: utf-8 -*-
"""内置资源年级×学科授权与生命周期回归（2026-11-04）。

覆盖：
- 交集+通配授权语义（年级与任教学科同时命中）；
- 授权记录覆盖旧 is_public（管理员收紧后立即生效）；
- 学生端跟随任课教师授权范围（多班级各自生效）；
- 管理端单资源授权 / 批量授权路由与非法输入；
- 内置资源删除=停用（墓碑，重启种子不复活）与恢复；
- 管理员对内置资源元数据编辑持久、教师资源库按授权展示。
"""
import uuid

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (Class, ClassroomSession, Log, Resource, Student,
                        Subject, Teacher, TeachingSession, SystemConfig,
                        resource_audience, resource_share, teacher_class,
                        teacher_subject)
from app.blueprints.chem_lab import (CHEM_LAB_URL,
                                     ensure_chem_lab_resource)
from app.services.resource_access import (student_classroom_scoped_resources,
                                          teacher_visible_resources)

CSRF = 'audience-csrf'


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


def _audience_rows(res_id):
    return db.session.execute(resource_audience.select().where(
        resource_audience.c.resource_id == res_id)).fetchall()


def _cleanup(app, ids):
    with app.app_context():
        res_ids = list(ids.get('resources', []))
        if res_ids:
            TeachingSession.query.filter(
                TeachingSession.resource_id.in_(res_ids)).delete(
                    synchronize_session=False)
            db.session.execute(resource_audience.delete().where(
                resource_audience.c.resource_id.in_(res_ids)))
            db.session.execute(resource_share.delete().where(
                resource_share.c.resource_id.in_(res_ids)))
            Resource.query.filter(Resource.id.in_(res_ids)).delete(
                synchronize_session=False)
        stu_ids = list(ids.get('students', []))
        if stu_ids:
            Student.query.filter(Student.id.in_(stu_ids)).delete(
                synchronize_session=False)
        tids = list(ids.get('teachers', []))
        if tids:
            from app.models import teacher_class
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id.in_(tids)))
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id.in_(tids)))
            Teacher.query.filter(Teacher.id.in_(tids)).delete(
                synchronize_session=False)
        cls_ids = list(ids.get('classes', []))
        if cls_ids:
            ClassroomSession.query.filter(
                ClassroomSession.class_id.in_(cls_ids)).delete(
                    synchronize_session=False)
            Class.query.filter(Class.id.in_(cls_ids)).delete(
                synchronize_session=False)
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


def _setup(app, sfx):
    ids = {'classes': [], 'students': [], 'teachers': [],
           'resources': []}
    with app.app_context():
        phys = Subject.query.filter_by(name='物理').first()
        chem = Subject.query.filter_by(name='化学').first()
        if not phys:
            phys = Subject(name='物理', sort_order=91)
            db.session.add(phys)
        if not chem:
            chem = Subject(name='化学', sort_order=91)
            db.session.add(chem)
        db.session.flush()

        def mk_teacher(name, grade, subject_ids):
            t = Teacher(username=f'__aud_{name}_{sfx}',
                        display_name=f'授权{name}', grade=grade)
            t.set_password('pass123456')
            db.session.add(t)
            db.session.flush()
            for sid in subject_ids:
                db.session.execute(teacher_subject.insert().values(
                    teacher_id=t.id, subject_id=sid))
            return t

        t_phys = mk_teacher('phys', '高一', [phys.id])
        t_chem = mk_teacher('chem', '高二', [chem.id])
        t_none = mk_teacher('none', '', [])
        cls1 = Class(name=f'__aud_c1_{sfx}')
        cls2 = Class(name=f'__aud_c2_{sfx}')
        db.session.add_all([cls1, cls2])
        db.session.flush()
        t_phys.classes.append(cls1)
        t_chem.classes.append(cls2)
        stu1 = Student(name='授权学生1', student_number=f'__aud_s1_{sfx}',
                       student_class=cls1.name, has_changed_password=True)
        stu2 = Student(name='授权学生2', student_number=f'__aud_s2_{sfx}',
                       student_class=cls2.name, has_changed_password=True)
        stu1.set_password('pass123456')
        stu2.set_password('pass123456')
        db.session.add_all([stu1, stu2])
        db.session.flush()
        stu1.class_id = cls1.id
        stu2.class_id = cls2.id
        db.session.add_all([
            ClassroomSession(class_id=cls1.id, is_active=True),
            ClassroomSession(class_id=cls2.id, is_active=True)])
        res = Resource(
            title=f'__aud_res_{sfx}', url='',
            subject_id=phys.id, is_builtin=True,
            builtin_key=f'__aud_builtin_{sfx}',
            show_in_student=True, show_in_classroom=True,
            creator_type='admin', creator_name='管理员')
        db.session.add(res)
        db.session.flush()
        db.session.add_all([
            TeachingSession(resource_id=res.id, teacher_id=t_phys.id,
                            teacher_name='授权phys', class_id=cls1.id,
                            status='active'),
            TeachingSession(resource_id=res.id, teacher_id=t_chem.id,
                            teacher_name='授权chem', class_id=cls2.id,
                            status='active'),
        ])
        db.session.commit()
        ids.update(
            phys=phys.id, chem=chem.id,
            t_phys=t_phys.id, t_chem=t_chem.id, t_none=t_none.id,
            cls1=cls1.id, cls2=cls2.id, stu1=stu1.id, stu2=stu2.id,
            resources=[res.id])
        ids['classes'] = [cls1.id, cls2.id]
        ids['students'] = [stu1.id, stu2.id]
        ids['teachers'] = [t_phys.id, t_chem.id, t_none.id]
    return ids


def _visible_ids(app, teacher_id, classroom=True):
    with app.app_context():
        return {r.id for r in teacher_visible_resources(
            teacher_id, is_admin=False, mode='readonly',
            classroom=classroom).all()}


def test_audience_intersection_and_wildcard(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup(app, sfx)
    admin = _client(app, is_admin=True)
    res_id = ids['resources'][0]
    try:
        def save(data):
            resp = _post(admin, f'/admin/resources/{res_id}/audience', data)
            assert resp.status_code in (302, 303)

        with app.app_context():
            assert not _audience_rows(res_id)  # 未配置：默认不可用

        # 高一 × 物理：仅物理教师（高一）命中
        save({'grades': ['高一'], 'subject_ids': [str(ids['phys'])]})
        assert res_id in _visible_ids(app, ids['t_phys'])
        assert res_id not in _visible_ids(app, ids['t_chem'])
        assert res_id not in _visible_ids(app, ids['t_none'])
        # 课堂页门禁：命中者可直接进入（含不带 mode 的书签链接），
        # 未命中者仍 404（fail-closed）
        phys_client = _client(app, is_teacher=True, teacher_id=ids['t_phys'],
                              teacher_name='授权phys', teacher_mode='edit')
        chem_client = _client(app, is_teacher=True, teacher_id=ids['t_chem'],
                              teacher_name='授权chem', teacher_mode='edit')
        assert phys_client.get(f'/study/lesson/{res_id}').status_code == 200
        assert phys_client.get(
            f'/study/lesson/{res_id}?mode=classroom').status_code == 200
        assert chem_client.get(f'/study/lesson/{res_id}').status_code == 404
        assert chem_client.get(
            f'/study/lesson/{res_id}?mode=classroom').status_code == 404

        # 高一 × 不限学科：高中一年级任何学科教师命中
        save({'grades': ['高一'], 'all_subjects': '1'})
        assert res_id in _visible_ids(app, ids['t_phys'])
        assert res_id not in _visible_ids(app, ids['t_chem'])
        assert res_id not in _visible_ids(app, ids['t_none'])

        # 不限年级 × 化学：化学教师命中（初二/高三同理）
        save({'all_grades': '1', 'subject_ids': [str(ids['chem'])]})
        assert res_id not in _visible_ids(app, ids['t_phys'])
        assert res_id in _visible_ids(app, ids['t_chem'])
        assert res_id not in _visible_ids(app, ids['t_none'])

        # 不限年级 × 不限学科：全体教师命中
        save({'all_grades': '1', 'all_subjects': '1'})
        for tid in (ids['t_phys'], ids['t_chem'], ids['t_none']):
            assert res_id in _visible_ids(app, tid)
        with app.app_context():
            rows = _audience_rows(res_id)
            assert len(rows) == 1 and rows[0].grade is None
            assert rows[0].subject_id is None

        # 跨学科显式授权：高一 × 物理 也允许化学教师使用？
        # 交集语义下不命中（教师任教学科不匹配），符合“按学科授权”定义
        save({'grades': ['高一'], 'subject_ids': [str(ids['phys'])]})
        assert res_id not in _visible_ids(app, ids['t_chem'])
    finally:
        _cleanup(app, ids)


def test_audience_overrides_legacy_is_public(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup(app, sfx)
    admin = _client(app, is_admin=True)
    res_id = ids['resources'][0]
    try:
        with app.app_context():
            db.session.get(Resource, res_id).is_public = True
            db.session.commit()
        # 无授权记录：旧 is_public 生效，全体可见
        assert res_id in _visible_ids(app, ids['t_phys'])
        assert res_id in _visible_ids(app, ids['t_chem'])
        # 收紧为 高一×物理：is_public 被授权记录覆盖
        _post(admin, f'/admin/resources/{res_id}/audience',
              {'grades': ['高一'], 'subject_ids': [str(ids['phys'])]})
        assert res_id in _visible_ids(app, ids['t_phys'])
        assert res_id not in _visible_ids(app, ids['t_chem'])
        assert res_id not in _visible_ids(app, ids['t_none'])
    finally:
        _cleanup(app, ids)


def test_student_scope_follows_teacher_audience(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup(app, sfx)
    admin = _client(app, is_admin=True)
    res_id = ids['resources'][0]
    try:
        _post(admin, f'/admin/resources/{res_id}/audience',
              {'grades': ['高一'], 'subject_ids': [str(ids['phys'])]})
        with app.app_context():
            scoped1 = student_classroom_scoped_resources(ids['cls1'])
            scoped2 = student_classroom_scoped_resources(ids['cls2'])
            assert scoped1 is not None and scoped2 is not None
            assert res_id in {r.id for r in scoped1}
            assert res_id not in {r.id for r in scoped2}
        # 学生页面口径一致
        stu1 = _client(app, student_id=ids['stu1'], student_name='授权学生1')
        stu2 = _client(app, student_id=ids['stu2'], student_name='授权学生2')
        assert f'__aud_res_{sfx}' in stu1.get('/study').get_data(as_text=True)
        assert f'__aud_res_{sfx}' not in stu2.get('/study').get_data(
            as_text=True)
    finally:
        _cleanup(app, ids)


def test_admin_audience_routes_and_validation(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup(app, sfx)
    admin = _client(app, is_admin=True)
    teacher = _client(app, is_teacher=True, teacher_id=ids['t_phys'],
                      teacher_name='授权phys', teacher_mode='readonly')
    res_id = ids['resources'][0]
    try:
        # 非法：既未选年级也未勾选不限
        resp = _post(admin, f'/admin/resources/{res_id}/audience',
                     {'all_subjects': '1'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert not _audience_rows(res_id)
        # 非法学科 id
        resp = _post(admin, f'/admin/resources/{res_id}/audience',
                     {'all_grades': '1', 'subject_ids': ['999999']})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert not _audience_rows(res_id)
        # 非管理员不可修改
        resp = _post(teacher, f'/admin/resources/{res_id}/audience',
                     {'all_grades': '1', 'all_subjects': '1'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert not _audience_rows(res_id)
        # 批量授权两个资源
        with app.app_context():
            res2 = Resource(
                title=f'__aud_res2_{sfx}', url='', subject_id=ids['chem'],
                is_builtin=True, builtin_key=f'__aud_builtin2_{sfx}',
                show_in_student=True, show_in_classroom=True,
                creator_type='admin', creator_name='管理员')
            db.session.add(res2)
            db.session.commit()
            ids['resources'].append(res2.id)
        resp = _post(admin, '/admin/resources/audience', {
            'resource_ids': [str(res_id)],
            'all_grades': '1', 'subject_ids': [str(ids['chem'])]})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert len(_audience_rows(res_id)) == 1
            log = Log.query.filter_by(action='批量授权内置资源').order_by(
                Log.id.desc()).first()
            assert log is not None
    finally:
        _cleanup(app, ids)


def test_builtin_delete_tombstone_and_restore(app):
    with app.app_context():
        # 清除历史失败运行可能残留的墓碑，保证用例可重复
        SystemConfig.set('builtin_suppressed:chem_lab', '0')
        db.session.commit()
        ensure_chem_lab_resource()
    admin = _client(app, is_admin=True, admin_name='管理员')
    with app.app_context():
        phys = Resource.query.filter(
            Resource.url == CHEM_LAB_URL).first()
        assert phys is not None and phys.is_builtin
        phys_id = phys.id
        key = phys.builtin_key
        assert _audience_rows(phys_id)  # 种子默认不限年级×不限学科
    try:
        # 管理员删除 = 停用（墓碑）
        resp = _post(admin, f'/admin/resources/delete/{phys_id}')
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert db.session.get(Resource, phys_id) is None
            assert SystemConfig.get(f'builtin_suppressed:{key}') == '1'
        # 重启种子不复活
        with app.app_context():
            ensure_chem_lab_resource()
        with app.app_context():
            assert Resource.query.filter(
                Resource.url == CHEM_LAB_URL).first() \
                is None
        # 管理端恢复入口
        resp = _post(admin, '/admin/builtin-resources/restore', {'key': key})
        assert resp.status_code in (302, 303)
        with app.app_context():
            row = Resource.query.filter(
                Resource.url == CHEM_LAB_URL).first()
            assert row is not None and row.is_builtin
            assert SystemConfig.get(f'builtin_suppressed:{key}') != '1'
            assert _audience_rows(row.id)
    finally:
        with app.app_context():
            # 兜底：清除墓碑并确保统一入口存在（不影响后续用例）
            SystemConfig.set('builtin_suppressed:chem_lab', '0')
            db.session.commit()
            ensure_chem_lab_resource()


def test_admin_full_permissions_on_builtin(app):
    with app.app_context():
        ensure_chem_lab_resource()
        phys = Resource.query.filter(
            Resource.url == CHEM_LAB_URL).first()
        phys_id = phys.id
        chem = Subject.query.filter_by(name='化学').first()
        chem_id = chem.id if chem else None
        old_title = phys.title
        old_subject = phys.subject_id
    admin = _client(app, is_admin=True, admin_name='管理员')
    try:
        data = {
            'title': '化学仿真(校本名)',
            'subject_id': str(chem_id) if chem_id else '',
            'show_in_student': '1', 'show_in_classroom': '1',
            'quiz_mode': 'none',
        }
        resp = _post(admin, f'/admin/resources/edit/{phys_id}', data)
        assert resp.status_code in (302, 303)
        with app.app_context():
            phys = db.session.get(Resource, phys_id)
            assert phys.title == '化学仿真(校本名)'
            if chem_id:
                assert phys.subject_id == chem_id
        # 启动种子不覆盖管理员编辑
        with app.app_context():
            ensure_chem_lab_resource()
        with app.app_context():
            phys = db.session.get(Resource, phys_id)
            assert phys.title == '化学仿真(校本名)'
        # 授权卡片在编辑页可见（内置资源）
        page = admin.get(f'/admin/resources/edit/{phys_id}')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '课堂授权范围' in text and 'audienceCard' in text
        # 批量授权页可见内置资源与当前范围
        page = admin.get('/admin/resources/audience')
        assert page.status_code == 200
        assert '内置资源批量授权' in page.get_data(as_text=True)
    finally:
        with app.app_context():
            phys = db.session.get(Resource, phys_id)
            if phys:
                phys.title = old_title
                phys.subject_id = old_subject
                db.session.commit()


def test_rename_subject_preserves_teacher_scope_and_student_access(app):
    """原地改名只换名称，不换学科 id；共享资源仍随任课教师可见。"""
    sfx = uuid.uuid4().hex[:8]
    old_name = f'__rn_old_{sfx}'
    new_name = f'__rn_new_{sfx}'
    with app.app_context():
        subject = Subject(name=old_name)
        owner = Teacher(username=f'__rn_owner_{sfx}', display_name='资源教师')
        owner.set_password('pass123456')
        teacher = Teacher(username=f'__rn_teacher_{sfx}', display_name='任课教师')
        teacher.set_password('pass123456')
        cls = Class(name=f'__rn_cls_{sfx}')
        student = Student(name='改名测试学生',
                          student_number=f'__rn_stu_{sfx}',
                          student_class=cls.name, has_changed_password=True)
        student.set_password('pass123456')
        db.session.add_all([subject, owner, teacher, cls, student])
        db.session.flush()
        student.class_id = cls.id
        db.session.execute(teacher_class.insert().values(
            teacher_id=teacher.id, class_id=cls.id))
        db.session.execute(teacher_subject.insert().values(
            teacher_id=teacher.id, subject_id=subject.id))
        resource = Resource(
            title=f'__rn_res_{sfx}', url='', subject_id=subject.id,
            creator_type='teacher', creator_teacher_id=owner.id,
            creator_name='资源教师', is_public=False,
            show_in_student=True, show_in_classroom=True)
        db.session.add(resource)
        db.session.flush()
        db.session.execute(resource_share.insert().values(
            resource_id=resource.id, teacher_id=teacher.id))
        db.session.commit()
        ids = {'subject': subject.id, 'resource': resource.id,
               'teachers': [owner.id, teacher.id], 'students': [student.id],
               'classes': [cls.id], 'resources': [resource.id]}
    cache.clear()
    try:
        student_client = _client(app, student_id=ids['students'][0],
                                 student_name='改名测试学生')
        assert student_client.get(
            f"/study/lesson/{ids['resource']}").status_code == 200
        admin = _client(app, is_admin=True, admin_name='管理员')
        resp = _post(admin, '/admin/subjects/rename',
                     {'sid': ids['subject'], 'name': new_name})
        assert resp.status_code in (301, 302, 303, 307, 308)
        with app.app_context():
            subject = db.session.get(Subject, ids['subject'])
            assert subject is not None and subject.name == new_name
            assert db.session.execute(teacher_subject.select().where(
                teacher_subject.c.teacher_id == ids['teachers'][1],
                teacher_subject.c.subject_id == ids['subject'])).first()
            resource = db.session.get(Resource, ids['resource'])
            assert resource.subject_id == ids['subject']
        assert student_client.get(
            f"/study/lesson/{ids['resource']}").status_code == 200
        assert f'__rn_res_{sfx}' in student_client.get('/study').get_data(
            as_text=True)
    finally:
        _cleanup(app, ids)
        with app.app_context():
            Subject.query.filter_by(id=ids['subject']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_rename_subject_rejects_existing_name(app):
    sfx = uuid.uuid4().hex[:8]
    name_a = f'__rn_dup_a_{sfx}'
    name_b = f'__rn_dup_b_{sfx}'
    with app.app_context():
        a = Subject(name=name_a)
        b = Subject(name=name_b)
        db.session.add_all([a, b])
        db.session.commit()
        ids = {'a': a.id, 'b': b.id}
    cache.clear()
    try:
        admin = _client(app, is_admin=True, admin_name='管理员')
        resp = _post(admin, '/admin/subjects/rename',
                     {'sid': ids['a'], 'name': name_b})
        assert resp.status_code in (301, 302, 303, 307, 308)
        with app.app_context():
            assert db.session.get(Subject, ids['a']).name == name_a
    finally:
        with app.app_context():
            Subject.query.filter(Subject.id.in_(
                [ids['a'], ids['b']])).delete(synchronize_session=False)
            db.session.commit()
            cache.clear()
