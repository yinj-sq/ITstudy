# -*- coding: utf-8 -*-
"""V6.0 生产就绪回归（2026-11-04）。

覆盖本轮审查修复：
1. 静态路径双斜杠/点段绕过（匿名读私有文件）；
2. 教师私有静态文件按任课班级收窄；
3. 删除学生/资源/学科时问卷答卷级联；
4. 删除班级先解除学生小组引用；
5. 非作息时段不再清空课堂会话/登录状态；
6. 历史考勤不再用当前名册伪造 offline；
7. 静态资源预压缩直出（gzip / Range 回退）；
8. 课堂图板保存限资源所有者；
9. 考试列表过滤已禁用试卷；
10. 缓存目录相对路径按项目根解析。
"""
import gzip
import json
import pathlib
import uuid
from datetime import date, datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, ClassroomSession, ClassroomSetting, Exam,
                        Resource, Student, StudyGroup,
                        Survey, SurveyAnswer, SurveyQuestion, Teacher,
                        teacher_class)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'v6-production-1104-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, **kwargs):
    kwargs.setdefault('headers', {})['X-CSRFToken'] = CSRF
    return client.post(path, **kwargs)


def test_static_double_slash_and_dot_segment_rejected(app):
    sfx = uuid.uuid4().hex[:8]
    sid = 960000 + int(sfx[:4], 16) % 1000
    rel_dir = UPLOADS / 'cloud_drive' / str(sid)
    rel_dir.mkdir(parents=True, exist_ok=True)
    probe = rel_dir / '__v6_probe.txt'
    probe.write_text('private-v6', encoding='utf-8')
    client = app.test_client()
    try:
        for path in (
            f'/static/uploads/cloud_drive/{sid}/__v6_probe.txt',
            f'/static/uploads//cloud_drive/{sid}/__v6_probe.txt',
            f'/static/uploads/./cloud_drive/{sid}/__v6_probe.txt',
            f'/static/uploads/cloud_drive/{sid}/../{sid}/__v6_probe.txt',
        ):
            assert client.get(path).status_code == 403, path
    finally:
        probe.unlink(missing_ok=True)


def test_teacher_private_static_scope(app):
    sfx = uuid.uuid4().hex[:8]
    names = {k: f'__v6_{k}_{sfx}' for k in
             ('c1', 'c2', 's1', 's2', 't1', 't2')}
    ids = {}
    try:
        with app.app_context():
            c1 = Class(name=names['c1'])
            c2 = Class(name=names['c2'])
            db.session.add_all([c1, c2])
            db.session.flush()
            t1 = Teacher(username=names['t1'], password_hash='x')
            t2 = Teacher(username=names['t2'], password_hash='x')
            db.session.add_all([t1, t2])
            db.session.flush()
            db.session.execute(teacher_class.insert().values(
                teacher_id=t1.id, class_id=c1.id))
            s1 = Student(name=names['s1'], student_number=names['s1'],
                         class_id=c1.id)
            s2 = Student(name=names['s2'], student_number=names['s2'],
                         class_id=c2.id)
            db.session.add_all([s1, s2])
            db.session.commit()
            ids.update(t1=t1.id, t2=t2.id, s1=s1.id, s2=s2.id)
        d1 = UPLOADS / 'cloud_drive' / str(ids['s1'])
        d2 = UPLOADS / 'cloud_drive' / str(ids['s2'])
        d1.mkdir(parents=True, exist_ok=True)
        d2.mkdir(parents=True, exist_ok=True)
        (d1 / '__v6_own.txt').write_text('own', encoding='utf-8')
        (d2 / '__v6_other.txt').write_text('other', encoding='utf-8')
        other_path = f'/static/uploads/cloud_drive/{ids["s2"]}/__v6_other.txt'
        own_path = f'/static/uploads/cloud_drive/{ids["s1"]}/__v6_own.txt'
        teacher = _client(app, is_teacher=True, teacher_id=ids['t1'],
                          teacher_mode='edit')
        assert teacher.get(own_path).status_code == 200
        assert teacher.get(other_path).status_code == 403
        assert app.test_client().get(other_path).status_code == 403
    finally:
        for sid in (ids.get('s1'), ids.get('s2')):
            if sid:
                folder = UPLOADS / 'cloud_drive' / str(sid)
                if folder.exists():
                    for f in folder.glob('__v6_*.txt'):
                        f.unlink(missing_ok=True)
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
        with app.app_context():
            from app.models import teacher_class as _tc
            tids = [t.id for t in Teacher.query.filter(
                Teacher.username.like(f'%{sfx}')).all()]
            if tids:
                db.session.execute(_tc.delete().where(_tc.c.teacher_id.in_(tids)))
            Student.query.filter(
                Student.student_number.like(f'%{sfx}')).delete(
                synchronize_session=False)
            Teacher.query.filter(
                Teacher.username.like(f'%{sfx}')).delete(
                synchronize_session=False)
            Class.query.filter(Class.name.like(f'%{sfx}')).delete(
                synchronize_session=False)
            db.session.commit()


def test_survey_answers_do_not_block_student_or_resource_delete(app):
    sfx = uuid.uuid4().hex[:8]
    try:
        with app.app_context():
            cls = Class(name=f'__v6_survey_class_{sfx}')
            db.session.add(cls)
            db.session.flush()
            stu = Student(name=f'__v6_survey_stu_{sfx}', class_id=cls.id,
                          student_number=f'__v6_survey_stu_{sfx}')
            res = Resource(title=f'__v6_survey_res_{sfx}',
                           url='/static/uploads/__v6_survey_dir/')
            db.session.add_all([stu, res])
            db.session.flush()
            survey = Survey(resource_id=res.id, title='问卷')
            db.session.add(survey)
            db.session.flush()
            q = SurveyQuestion(survey_id=survey.id, q_type='text', title='题')
            db.session.add(q)
            db.session.flush()
            db.session.add(SurveyAnswer(survey_id=survey.id, student_id=stu.id,
                                        answers='{}'))
            db.session.commit()
            stu_id, res_id, survey_id = stu.id, res.id, survey.id

            from app.blueprints.class_management import (
                _cleanup_student_records_batch)
            _cleanup_student_records_batch([stu_id])
            Student.query.filter_by(id=stu_id).delete(
                synchronize_session=False)
            db.session.commit()
            assert SurveyAnswer.query.filter_by(student_id=stu_id).count() == 0

            from app.blueprints.resources import _delete_surveys_for_resources
            _delete_surveys_for_resources([res_id])
            db.session.commit()
            assert Survey.query.filter_by(id=survey_id).count() == 0
            assert SurveyQuestion.query.filter_by(survey_id=survey_id).count() == 0
            Resource.query.filter_by(id=res_id).delete(synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
            db.session.commit()
    finally:
        with app.app_context():
            db.session.rollback()
            SurveyAnswer.query.filter(
                SurveyAnswer.answers == '{}').delete(
                synchronize_session=False)
            db.session.commit()


def test_delete_class_clears_student_group_reference(app):
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__v6_group_class_{sfx}')
        db.session.add(cls)
        db.session.flush()
        grp = StudyGroup(name=f'g{sfx[:8]}', class_id=cls.id)
        db.session.add(grp)
        db.session.flush()
        stu = Student(name=f'__v6_group_stu_{sfx}', class_id=cls.id,
                      student_number=f'__v6_group_stu_{sfx}',
                      group_id=grp.id)
        db.session.add(stu)
        db.session.commit()
        cls_id = cls.id
    admin = _client(app, is_admin=True)
    resp = _post(admin, f'/admin/classes/{cls_id}/delete')
    assert resp.status_code in (200, 302)
    with app.app_context():
        assert db.session.get(Class, cls_id) is None
        assert StudyGroup.query.filter_by(class_id=cls_id).count() == 0


def test_no_period_auto_switch_keeps_active_sessions(app, monkeypatch):
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        from app.blueprints import classroom as classroom_module
        cls = Class(name=f'__v6_auto_class_{sfx}')
        db.session.add(cls)
        db.session.flush()
        stu = Student(name=f'__v6_auto_stu_{sfx}', class_id=cls.id,
                      student_number=f'__v6_auto_stu_{sfx}',
                      ip_address='10.0.0.8', login_time=datetime.now())
        setting = ClassroomSetting.query.first() or ClassroomSetting()
        if setting.id is None:
            db.session.add(setting)
        original = (setting.auto_switch, setting.active_class_id)
        setting.auto_switch = True
        setting.active_class_id = cls.id
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True,
                                        auto_switch=True))
        db.session.add(stu)
        db.session.commit()
        cls_id, stu_id = cls.id, stu.id

        monkeypatch.setattr(classroom_module, 'get_schedules_cached', lambda: [])
        classroom_module._sync_auto_sessions(setting, datetime.now())

        session_row = ClassroomSession.query.filter_by(class_id=cls_id).first()
        stu = db.session.get(Student, stu_id)
        assert session_row and session_row.is_active is True
        assert stu.ip_address == '10.0.0.8'
        assert stu.login_time is not None

        ClassroomSession.query.filter_by(class_id=cls_id).delete(
            synchronize_session=False)
        Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
        setting.auto_switch, setting.active_class_id = original
        db.session.commit()
        Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
        db.session.commit()


def test_attendance_history_does_not_fabricate_offline(app):
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        from app.services.attendance_service import get_history
        cls = Class(name=f'__v6_att_class_{sfx}')
        db.session.add(cls)
        db.session.flush()
        stu = Student(name=f'__v6_att_stu_{sfx}', class_id=cls.id,
                      student_number=f'__v6_att_stu_{sfx}')
        db.session.add(stu)
        db.session.commit()
        cls_id = cls.id
        yesterday = date.today() - timedelta(days=1)
        records, stats = get_history(yesterday, cls_id)
        assert records == []
        assert stats['total'] == 0
        Student.query.filter_by(class_id=cls_id).delete(
            synchronize_session=False)
        Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
        db.session.commit()


def test_precompressed_static_serving(app):
    src = ROOT / 'static' / 'js' / 'ui-feedback.js'
    if not src.exists():
        pytest.skip('缺少静态资源样本')
    client = app.test_client()
    gz_resp = client.get('/static/js/ui-feedback.js',
                         headers={'Accept-Encoding': 'gzip'})
    assert gz_resp.status_code == 200
    if (ROOT / 'static' / 'js' / 'ui-feedback.js.gz').exists():
        assert gz_resp.headers.get('Content-Encoding') == 'gzip'
        assert gzip.decompress(gz_resp.data) == src.read_bytes()
    identity = client.get('/static/js/ui-feedback.js')
    assert identity.status_code == 200
    assert not identity.headers.get('Content-Encoding')
    ranged = client.get('/static/js/ui-feedback.js',
                        headers={'Accept-Encoding': 'gzip',
                                 'Range': 'bytes=0-10'})
    assert ranged.status_code in (206, 200)
    assert not ranged.headers.get('Content-Encoding')


def test_mindmap_save_requires_resource_ownership(app):
    sfx = uuid.uuid4().hex[:8]
    try:
        with app.app_context():
            owner = Teacher(username=f'__v6_mm_own_{sfx}', password_hash='x')
            other = Teacher(username=f'__v6_mm_oth_{sfx}', password_hash='x')
            db.session.add_all([owner, other])
            db.session.flush()
            res = Resource(title=f'__v6_mm_res_{sfx}',
                           url=f'/static/uploads/__v6_mm_dir_{sfx}/',
                           creator_type='teacher', creator_teacher_id=owner.id,
                           show_in_classroom=True)
            db.session.add(res)
            db.session.commit()
            owner_id, other_id, res_id = owner.id, other.id, res.id
        other_client = _client(app, is_teacher=True, teacher_id=other_id,
                               teacher_mode='edit')
        resp = _post(other_client,
                     f'/study/lesson/{res_id}/mindmap/save',
                     json={'name': 'x', 'data': {'root': {}}})
        assert resp.status_code == 403
        owner_client = _client(app, is_teacher=True, teacher_id=owner_id,
                               teacher_mode='edit')
        resp = _post(owner_client,
                     f'/study/lesson/{res_id}/mindmap/save',
                     json={'name': f'__v6_{sfx}', 'data': {'root': {}}})
        assert resp.status_code == 200
    finally:
        with app.app_context():
            Resource.query.filter(Resource.title.like(f'%{sfx}')).delete(
                synchronize_session=False)
            Teacher.query.filter(
                Teacher.username.like(f'%{sfx}')).delete(
                synchronize_session=False)
            db.session.commit()
        folder = UPLOADS / f'__v6_mm_dir_{sfx}'
        if folder.exists():
            for f in folder.glob('mindmap-*.json'):
                f.unlink(missing_ok=True)
            try:
                folder.rmdir()
            except OSError:
                pass


def test_exam_list_filters_disabled(app):
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        exam = Exam(name=f'__v6_disabled_{sfx}', is_active=True,
                    is_visible=True, is_enabled=False)
        db.session.add(exam)
        db.session.commit()
        exam_id = exam.id
    client = _client(app)
    body = client.get('/exam').get_data(as_text=True)
    assert f'__v6_disabled_{sfx}' not in body
    with app.app_context():
        Exam.query.filter_by(id=exam_id).delete(synchronize_session=False)
        db.session.commit()


def test_cache_dir_is_absolute():
    from app.config import Config
    assert pathlib.Path(Config.CACHE_DIR).is_absolute()


def test_student_welcome_banner_shown_only_once(app):
    """欢迎横幅只在登录后第一次渲染出现，切换页面不再重复提示。"""
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        stu = Student(name=f'__v6_welcome_{sfx}',
                      student_number=f'__v6_welcome_{sfx}',
                      has_changed_password=True)
        db.session.add(stu)
        db.session.commit()
        stu_id = stu.id
    try:
        client = _client(app, student_id=stu_id,
                         student_name=f'__v6_welcome_{sfx}',
                         show_welcome=True)
        first = client.get('/study').get_data(as_text=True)
        assert '欢迎回来' in first
        second = client.get('/exam').get_data(as_text=True)
        assert '欢迎回来' not in second
    finally:
        with app.app_context():
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()


def test_lesson_tree_visible_document_overrides_file_level_hide(app):
    """课堂编排勾选「学生可见」后，PDF 预览/播放不再被文件级 show=false 拦截。

    直链（/static/uploads/...）仍保持文件级隐藏；只有章节树内且
    visible.student=true 的条目可通过课堂条目路由读取。
    """
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__v6_lesson_doc_{sfx}'
    folder = UPLOADS / dir_name
    folder.mkdir(parents=True, exist_ok=True)
    pdf_bytes = b'%PDF-1.4\n% v6 lesson doc\n'
    (folder / 'doc.pdf').write_bytes(pdf_bytes)
    (folder / 'hidden.pdf').write_bytes(b'%PDF-1.4\n% hidden\n')
    tree = [{
        'id': 'sec_v6', 'title': '第一章', 'type': 'section',
        'children': [],
        'items': [
            {'id': 'visible_doc', 'title': '可见文档', 'kind': 'doc',
             'src': 'doc.pdf', 'doc_category': 'guide',
             'visible': {'teacher': True, 'student': True}},
            {'id': 'hidden_doc', 'title': '隐藏文档', 'kind': 'doc',
             'src': 'hidden.pdf', 'doc_category': 'guide',
             'visible': {'teacher': True, 'student': False}},
        ],
    }]
    with app.app_context():
        stu = Student(name=f'__v6_lesson_stu_{sfx}',
                      student_number=f'__v6_lesson_stu_{sfx}',
                      has_changed_password=True)
        res = Resource(
            title=f'__v6_lesson_res_{sfx}',
            url=f'/static/uploads/{dir_name}/',
            show_in_student=True, show_in_classroom=True, is_public=True,
            file_permissions=json.dumps({
                'doc.pdf': {'show': False, 'download': False},
                'hidden.pdf': {'show': False, 'download': False},
            }, ensure_ascii=False),
            lesson_tree=json.dumps(tree, ensure_ascii=False))
        db.session.add_all([stu, res])
        db.session.commit()
        stu_id, res_id = stu.id, res.id
    try:
        client = _client(app, student_id=stu_id)
        page = client.get(f'/study/lesson/{res_id}')
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert 'visible_doc' in body and 'hidden_doc' not in body
        page.close()

        # 条目可见：预览壳与文件本体均可访问
        preview = client.get(
            f'/study/preview?lesson_res={res_id}&lesson_item=visible_doc&embed=1')
        assert preview.status_code == 200
        assert f'/study/lesson/{res_id}/item/visible_doc/file' in \
            preview.get_data(as_text=True)
        preview.close()
        raw = client.get(
            f'/study/lesson/{res_id}/item/visible_doc/file')
        assert raw.status_code == 200
        assert raw.data == pdf_bytes
        raw.close()

        # 条目隐藏 / 跨资源伪造 id：一律 404
        assert client.get(
            f'/study/preview?lesson_res={res_id}&lesson_item=hidden_doc'
        ).status_code == 404
        assert client.get(
            f'/study/lesson/{res_id}/item/hidden_doc/file'
        ).status_code == 404
        assert client.get(
            f'/study/lesson/{res_id}/item/visible_doc/pptist-cache'
        ).status_code == 404

        # 静态直链仍受文件级 show=false 约束
        assert client.get(
            f'/static/uploads/{dir_name}/doc.pdf').status_code == 403
    finally:
        with app.app_context():
            Resource.query.filter_by(id=res_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()
        for f in ('doc.pdf', 'hidden.pdf'):
            (folder / f).unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
