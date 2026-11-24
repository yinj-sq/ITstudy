# -*- coding: utf-8 -*-
"""学生资源可见性严格跟随授课教师（2026-11-04）。

回归用户反馈：
1. 学生端无法打开教师授权展示的 PPTX 文档，预览 403；
2. 学生端不应看到全部资源，只应看到当前授课教师学科/年级范围内的资源
   以及公开/内置允许公开的资源。

覆盖：
- 授课教师范围内资源即使 show_in_student=False，列表、课堂页、静态文件、
  在线预览仍可用；
- 文件级「展示」隐藏仍对学生生效（静态文件与预览均 403）；
- 范围外教师资源、教师其他学科资源不进入列表且直链 404/403；
- 公开资源不依赖授课教师，始终可用；
- 下课后教师范围失效，仅公开资源保留。
"""
import pathlib
import shutil
import uuid
from datetime import datetime

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (AccountPageView, AccountSession, AttendanceRecord,
                        Class, ClassroomSetting, ClassroomSession, Exam,
                        Homework, HomeworkSubmission, LearningActivity, Log,
                        Resource,
                        ResourceQuizResult, Result, Student, Subject, Survey,
                        Teacher, TeachingSession, homework_classes,
                        teacher_class, teacher_subject)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'student-scope-1104-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _invalidate(app):
    with app.app_context():
        from app.blueprints.resources import _invalidate_study_caches
        _invalidate_study_caches()


def test_student_resources_strictly_follow_teacher(app):
    sfx = uuid.uuid4().hex[:8]
    c1_name = f'__s1104_c1_{sfx}'
    c2_name = f'__s1104_c2_{sfx}'
    s1_name = f'__s1104_s1_{sfx}'
    s2_name = f'__s1104_s2_{sfx}'
    a_name = f'__s1104_a_{sfx}'
    b_name = f'__s1104_b_{sfx}'
    stu1_num = f'__s1104_stu1_{sfx}'
    stu2_num = f'__s1104_stu2_{sfx}'
    dir_teacher = f'__s1104_teacher_{sfx}'
    dir_public = f'__s1104_public_{sfx}'
    dir_other = f'__s1104_other_{sfx}'
    dir_a_other = f'__s1104_aother_{sfx}'
    dir_a_draft = f'__s1104_adraft_{sfx}'
    teacher_dir = UPLOADS / dir_teacher
    public_dir = UPLOADS / dir_public
    other_dir = UPLOADS / dir_other
    a_other_dir = UPLOADS / dir_a_other
    a_draft_dir = UPLOADS / dir_a_draft
    ids = {}
    try:
        for d in (teacher_dir, public_dir, other_dir, a_other_dir,
                  a_draft_dir):
            d.mkdir(parents=True, exist_ok=True)
        (teacher_dir / 'slides.pptx').write_bytes(b'PK\x03\x04teacher-pptx')
        (teacher_dir / 'hidden.pptx').write_bytes(b'PK\x03\x04hidden')
        (public_dir / 'public.pdf').write_bytes(b'%PDF-1.4 public')
        (other_dir / 'other.pdf').write_bytes(b'%PDF-1.4 other')
        (a_other_dir / 'aother.pdf').write_bytes(b'%PDF-1.4 aother')
        (a_draft_dir / 'draft.pdf').write_bytes(b'%PDF-1.4 draft')

        with app.app_context():
            c1 = Class(name=c1_name)
            c2 = Class(name=c2_name)
            s1 = Subject(name=s1_name, sort_order=940)
            s2 = Subject(name=s2_name, sort_order=941)
            a = Teacher(username=a_name, display_name='授课教师A',
                        grade='高一')
            a.set_password('pass123456')
            b = Teacher(username=b_name, display_name='其他教师B',
                        grade='高一')
            b.set_password('pass123456')
            a.subjects = [s1]
            b.subjects = [s2]
            a.classes = [c1]
            stu1 = Student(name='范围学生1', student_number=stu1_num,
                           student_class=c1_name, grade='高二',
                           has_changed_password=True)
            stu1.set_password('pass123456')
            stu2 = Student(name='范围学生2', student_number=stu2_num,
                           student_class=c2_name, grade='高一',
                           has_changed_password=True)
            stu2.set_password('pass123456')
            db.session.add_all([c1, c2, s1, s2, a, b, stu1, stu2])
            db.session.flush()
            stu1.class_id = c1.id
            stu2.class_id = c2.id

            def mk(title, subject_id, creator, url, public=False,
                   student_visible=True):
                r = Resource(
                    title=title, url=url, subject_id=subject_id,
                    show_in_student=student_visible,
                    show_in_classroom=True, quiz_mode='none',
                    is_public=public,
                    creator_type='teacher' if creator else 'admin',
                    creator_teacher_id=creator.id if creator else None,
                    creator_name=creator.display_name if creator else '管理员')
                db.session.add(r)
                return r

            r_teacher = mk(
                f'__s1104_r_teacher_{sfx}', s1.id, a,
                f'/static/uploads/{dir_teacher}/slides.pptx',
                student_visible=False)
            r_public = mk(
                f'__s1104_r_public_{sfx}', None, None,
                f'/static/uploads/{dir_public}/public.pdf', public=True)
            r_other = mk(
                f'__s1104_r_other_{sfx}', s2.id, b,
                f'/static/uploads/{dir_other}/other.pdf')
            r_a_other = mk(
                f'__s1104_r_aother_{sfx}', s2.id, a,
                f'/static/uploads/{dir_a_other}/aother.pdf')
            r_a_draft = mk(
                f'__s1104_r_adraft_{sfx}', s1.id, a,
                f'/static/uploads/{dir_a_draft}/draft.pdf',
                student_visible=False)
            r_a_draft.show_in_classroom = False
            db.session.flush()
            r_teacher.file_permissions = (
                '{"hidden.pptx": {"show": false, "download": true}}')
            db.session.add(TeachingSession(
                resource_id=r_teacher.id, teacher_id=a.id,
                teacher_name=a.display_name, class_id=c1.id,
                status='active'))
            db.session.add(ClassroomSession(class_id=c1.id, is_active=True))
            db.session.add(ClassroomSession(class_id=c2.id, is_active=True))
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
            ids.update(
                c1=c1.id, c2=c2.id, a=a.id, b=b.id,
                stu1=stu1.id, stu2=stu2.id,
                r_teacher=r_teacher.id, r_public=r_public.id,
                r_other=r_other.id, r_a_other=r_a_other.id,
                r_a_draft=r_a_draft.id)
        _invalidate(app)

        student1 = _client(app, student_id=ids['stu1'],
                           student_name='范围学生1')
        text = student1.get('/study').get_data(as_text=True)
        assert f'__s1104_r_teacher_{sfx}' in text
        assert f'__s1104_r_public_{sfx}' in text
        assert f'__s1104_r_other_{sfx}' not in text
        # 教师自建资源不再按学科/学生年级二次过滤（学生年级与教师档案
        # 不一致时也必须能看到老师自己的资源）
        assert f'__s1104_r_aother_{sfx}' in text
        assert f'__s1104_r_adraft_{sfx}' not in text

        api_ids = {item['id'] for item in student1.get(
            '/api/resources').get_json()['data']}
        assert ids['r_teacher'] in api_ids
        assert ids['r_public'] in api_ids
        assert ids['r_other'] not in api_ids
        assert ids['r_a_other'] in api_ids
        assert ids['r_a_draft'] not in api_ids

        # 教师授权展示的 PPTX：课堂页、静态文件、在线预览均可用
        assert student1.get(
            f'/study/lesson/{ids["r_teacher"]}').status_code == 200
        static_resp = student1.get(
            f'/static/uploads/{dir_teacher}/slides.pptx')
        assert static_resp.status_code == 200
        static_resp.close()
        preview = student1.get(
            f'/study/preview?file=/static/uploads/{dir_teacher}/'
            'slides.pptx&name=slides.pptx')
        assert preview.status_code == 200

        # 文件级「展示」隐藏仍生效
        assert student1.get(
            f'/static/uploads/{dir_teacher}/hidden.pptx').status_code == 403
        assert student1.get(
            f'/study/preview?file=/static/uploads/{dir_teacher}/'
            'hidden.pptx&name=hidden.pptx').status_code == 403

        # 公开资源不依赖授课教师
        pub_static = student1.get(
            f'/static/uploads/{dir_public}/public.pdf')
        assert pub_static.status_code == 200
        pub_static.close()
        assert student1.get(
            f'/study/preview?file=/static/uploads/{dir_public}/'
            'public.pdf&name=public.pdf').status_code == 200

        # 范围外资源：直链与预览均被拒绝
        assert student1.get(
            f'/study/lesson/{ids["r_other"]}').status_code == 404
        assert student1.get(
            f'/static/uploads/{dir_other}/other.pdf').status_code == 403
        assert student1.get(
            f'/study/preview?file=/static/uploads/{dir_other}/'
            'other.pdf&name=other.pdf').status_code == 403
        assert student1.get(
            f'/study/lesson/{ids["r_a_other"]}').status_code == 200
        assert student1.get(
            f'/static/uploads/{dir_a_other}/aother.pdf').status_code == 200
        # 教师两者都关闭的资源视为草稿：列表不出现、直链不可用
        assert student1.get(
            f'/study/lesson/{ids["r_a_draft"]}').status_code == 404
        assert student1.get(
            f'/static/uploads/{dir_a_draft}/draft.pdf').status_code == 403
        # 教师/管理员访问外链封装页不受学生范围校验影响
        teacher = _client(app, is_teacher=True, teacher_id=ids['a'],
                          teacher_name='授课教师A', teacher_mode='edit')
        assert teacher.get(
            '/study/link?resource_id=%s&url=https://example.com/x'
            % ids['r_teacher']).status_code == 200
        admin = _client(app, is_admin=True)
        assert admin.get(
            '/study/link?resource_id=%s&url=https://example.com/x'
            % ids['r_teacher']).status_code == 200

        # 同班学生但无授课教师：只保留公开资源
        student2 = _client(app, student_id=ids['stu2'],
                           student_name='范围学生2')
        text2 = student2.get('/study').get_data(as_text=True)
        assert f'__s1104_r_teacher_{sfx}' not in text2
        assert f'__s1104_r_other_{sfx}' not in text2
        assert f'__s1104_r_public_{sfx}' in text2
        assert student2.get(
            f'/study/lesson/{ids["r_teacher"]}').status_code == 404
        assert student2.get(
            f'/static/uploads/{dir_teacher}/slides.pptx').status_code == 403

        # 只结束教学记录、课堂仍开放：回退该班任课教师范围，资源仍可见
        with app.app_context():
            db.session.query(TeachingSession).filter_by(
                class_id=ids['c1']).update(
                    {TeachingSession.end_time: datetime.now(),
                     TeachingSession.status: 'ended'},
                    synchronize_session=False)
            db.session.commit()
        _invalidate(app)
        text3 = student1.get('/study').get_data(as_text=True)
        assert f'__s1104_r_teacher_{sfx}' in text3
        assert f'__s1104_r_aother_{sfx}' in text3
        assert f'__s1104_r_public_{sfx}' in text3
        assert student1.get(
            f'/study/lesson/{ids["r_teacher"]}').status_code == 200
        assert student1.get(
            f'/static/uploads/{dir_teacher}/slides.pptx').status_code == 200

        # 班级无任课教师时教师范围失效：仅公开资源保留
        with app.app_context():
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == ids['a'],
                teacher_class.c.class_id == ids['c1']))
            db.session.commit()
        _invalidate(app)
        text4 = student1.get('/study').get_data(as_text=True)
        assert f'__s1104_r_teacher_{sfx}' not in text4
        assert f'__s1104_r_aother_{sfx}' not in text4
        assert f'__s1104_r_public_{sfx}' in text4
        assert student1.get(
            f'/study/lesson/{ids["r_teacher"]}').status_code == 404
        assert student1.get(
            f'/static/uploads/{dir_teacher}/slides.pptx').status_code == 403
        assert student1.get(
            f'/study/preview?file=/static/uploads/{dir_teacher}/'
            'slides.pptx&name=slides.pptx').status_code == 403
        pub_after = student1.get(
            f'/static/uploads/{dir_public}/public.pdf')
        assert pub_after.status_code == 200
        pub_after.close()
    finally:
        with app.app_context():
            class_ids = [c.id for c in Class.query.filter(
                Class.name.in_([c1_name, c2_name])).all()]
            teacher_ids = [t.id for t in Teacher.query.filter(
                Teacher.username.in_([a_name, b_name])).all()]
            resource_ids = [r.id for r in Resource.query.filter(
                Resource.url.like(f'/static/uploads/__s1104_%_{sfx}/%')).all()]
            if class_ids:
                TeachingSession.query.filter(
                    TeachingSession.class_id.in_(class_ids)).delete(
                        synchronize_session=False)
                ClassroomSession.query.filter(
                    ClassroomSession.class_id.in_(class_ids)).delete(
                        synchronize_session=False)
            if resource_ids:
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
        for d in (teacher_dir, public_dir, other_dir, a_other_dir,
                  a_draft_dir):
            shutil.rmtree(d, ignore_errors=True)
        _invalidate(app)





def _clear_active_classrooms(app):
    """隔离上一条用例可能遗留的课堂会话/全局活动班级。"""
    with app.app_context():
        ClassroomSession.query.delete(synchronize_session=False)
        setting = ClassroomSetting.query.first()
        if setting:
            setting.active_class_id = None
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
        cache.clear()


def test_base_nav_and_anonymous_redirect(app):
    src = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'href="/student/home"' in src
    anon = app.test_client()
    resp = anon.get('/student/home', follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert resp.headers['Location'].endswith('/')


def test_student_home_and_root_redirect(app):
    _clear_active_classrooms(app)
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__home_cls_{sfx}')
        stu = Student(name='首页学生', student_number=f'__home_stu_{sfx}',
                      has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.commit()
        ids = {'cls': cls.id, 'stu': stu.id}
    cache.clear()
    try:
        client = _client(app, student_id=ids['stu'], student_name='首页学生')
        page = client.get('/student/home')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '今日学习' in text and '现在做什么' in text
        assert '请输入学号' not in text
        root = client.get('/', follow_redirects=False)
        assert root.status_code in (301, 302, 303, 307, 308)
        assert root.headers['Location'].endswith('/student/home')
    finally:
        with app.app_context():
            Student.query.filter_by(id=ids['stu']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_student_home_aggregates_tasks_and_path(app):
    _clear_active_classrooms(app)
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__home_data_cls_{sfx}')
        subject = Subject(name=f'__home_subj_{sfx}')
        teacher = Teacher(username=f'__home_t_{sfx}', display_name='首页教师')
        teacher.set_password('pass123456')
        stu = Student(name='数据学生', student_number=f'__home_data_{sfx}',
                      has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([subject, cls, teacher, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.execute(teacher_class.insert().values(
            teacher_id=teacher.id, class_id=cls.id))
        resource = Resource(
            title=f'__home_res_{sfx}', url='',
            subject_id=subject.id, creator_type='teacher',
            creator_teacher_id=teacher.id, creator_name='首页教师',
            is_public=False, show_in_student=True, show_in_classroom=True)
        db.session.add(resource)
        db.session.flush()
        hw = Homework(title=f'__home_hw_{sfx}',
                      subject_id=subject.id, teacher_id=teacher.id,
                      is_active=True)
        db.session.add(hw)
        db.session.flush()
        db.session.execute(homework_classes.insert().values(
            homework_id=hw.id, class_id=cls.id))
        activity = LearningActivity(
            resource_id=resource.id, title=f'__home_act_{sfx}',
            require_upload=True, is_active=True)
        survey = Survey(resource_id=resource.id,
                        title=f'__home_survey_{sfx}', status='published')
        exam = Exam(name=f'__home_exam_{sfx}', is_active=True,
                    is_visible=True, is_enabled=True, allow_view_results=True)
        db.session.add_all([activity, survey, exam])
        db.session.flush()
        quiz = ResourceQuizResult(
            student_id=stu.id, resource_id=resource.id,
            quiz_key='legacy', total_score=50, max_score=100)
        db.session.add(quiz)
        db.session.commit()
        ids = {'cls': cls.id, 'teacher': teacher.id, 'stu': stu.id,
               'subject': subject.id, 'resource': resource.id,
               'hw': hw.id, 'activity': activity.id,
               'survey': survey.id, 'exam': exam.id}
    cache.clear()
    try:
        client = _client(app, student_id=ids['stu'], student_name='数据学生')
        page = client.get('/student/home')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert f'__home_hw_{sfx}' in text
        assert f'__home_act_{sfx}' in text
        assert f'__home_survey_{sfx}' in text
        assert f'__home_exam_{sfx}' in text
        assert '学习路径' in text and '需加强' in text
        assert '5 分钟复习' in text
        # 进入课堂后主线变为当前课堂资源
        with app.app_context():
            db.session.add(ClassroomSession(class_id=ids['cls'],
                                            is_active=True))
            db.session.add(TeachingSession(
                resource_id=ids['resource'], teacher_id=ids['teacher'],
                teacher_name='首页教师', class_id=ids['cls'],
                status='active'))
            db.session.commit()
        cache.clear()
        with client.session_transaction() as sess:
            sess.update(student_id=ids['stu'], student_name='数据学生',
                        classroom_bound=True, csrf_token=CSRF)
        text2 = client.get('/student/home').get_data(as_text=True)
        assert '进入《' in text2 and f'__home_res_{sfx}' in text2
        assert '进入课堂' in text2
    finally:
        with app.app_context():
            TeachingSession.query.filter_by(
                resource_id=ids['resource']).delete(synchronize_session=False)
            ClassroomSession.query.filter_by(
                class_id=ids['cls']).delete(synchronize_session=False)
            Result.query.filter_by(exam_id=ids['exam']).delete(
                synchronize_session=False)
            ResourceQuizResult.query.filter_by(
                resource_id=ids['resource']).delete(synchronize_session=False)
            Survey.query.filter_by(id=ids['survey']).delete(
                synchronize_session=False)
            LearningActivity.query.filter_by(
                id=ids['activity']).delete(synchronize_session=False)
            HomeworkSubmission.query.filter_by(
                homework_id=ids['hw']).delete(synchronize_session=False)
            db.session.execute(homework_classes.delete().where(
                homework_classes.c.homework_id == ids['hw']))
            Homework.query.filter_by(id=ids['hw']).delete(
                synchronize_session=False)
            Exam.query.filter_by(id=ids['exam']).delete(
                synchronize_session=False)
            Resource.query.filter_by(id=ids['resource']).delete(
                synchronize_session=False)
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == ids['teacher']))
            Teacher.query.filter_by(id=ids['teacher']).delete(
                synchronize_session=False)
            Student.query.filter_by(id=ids['stu']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
            Subject.query.filter_by(id=ids['subject']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_class_ended_shows_login_reason(app):
    _clear_active_classrooms(app)
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__end_cls_{sfx}')
        stu = Student(name='下课学生', student_number=f'__end_stu_{sfx}',
                      has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.commit()
        ids = {'cls': cls.id, 'stu': stu.id}
    cache.clear()
    try:
        client = _client(app, student_id=ids['stu'], student_name='下课学生',
                         classroom_bound=True)
        resp = client.get('/student/home', follow_redirects=True)
        assert resp.status_code == 200
        assert '本节课已结束' in resp.get_data(as_text=True)
    finally:
        with app.app_context():
            Student.query.filter_by(id=ids['stu']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_root_redirects_admin_to_console(app):
    client = _client(app, is_admin=True, admin_name='管理员')
    resp = client.get('/', follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert resp.headers['Location'].endswith('/admin/dashboard')


def test_student_login_redirects_to_student_home(app):
    _clear_active_classrooms(app)
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__login_cls_{sfx}')
        stu = Student(name=f'__login_stu_{sfx}',
                      student_number=f'__login_num_{sfx}',
                      has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        db.session.commit()
        ids = {'cls': cls.id, 'stu': stu.id}
    cache.clear()
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['csrf_token'] = CSRF
        resp = client.post('/', data={
            'csrf_token': CSRF,
            'student_number': f'__login_num_{sfx}',
            'password': 'pass123456',
        }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        assert resp.headers['Location'].endswith('/student/home')
    finally:
        with app.app_context():
            AttendanceRecord.query.filter_by(student_id=ids['stu']).delete(
                synchronize_session=False)
            ClassroomSession.query.filter_by(class_id=ids['cls']).delete(
                synchronize_session=False)
            Student.query.filter_by(id=ids['stu']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_account_trail_multi_terminal_and_page_views(app):
    _clear_active_classrooms(app)
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        cls = Class(name=f'__trail_cls_{sfx}')
        stu = Student(name=f'__trail_stu_{sfx}',
                      student_number=f'__trail_num_{sfx}',
                      has_changed_password=True)
        stu.set_password('pass123456')
        db.session.add_all([cls, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        db.session.commit()
        ids = {'cls': cls.id, 'stu': stu.id}
    cache.clear()
    clients = []
    try:
        for _ in range(2):
            client = app.test_client()
            with client.session_transaction() as sess:
                sess['csrf_token'] = CSRF
            login = client.post('/', data={
                'csrf_token': CSRF,
                'student_number': f'__trail_num_{sfx}',
                'password': 'pass123456',
            }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
            assert login.status_code in (301, 302, 303, 307, 308)
            assert login.headers['Location'].endswith('/student/home')
            home = client.get('/student/home')
            assert home.status_code == 200
            clients.append(client)
        with app.app_context():
            sessions = AccountSession.query.filter_by(
                account_type='student', account_id=ids['stu']).order_by(
                    AccountSession.login_at).all()
            assert len(sessions) == 2
            assert all(row.login_ip for row in sessions)
            assert all((row.page_count or 0) >= 1 for row in sessions)
            for row in sessions:
                assert AccountPageView.query.filter_by(
                    session_id=row.id).count() >= 1
            open_ids = [row.id for row in sessions if row.logout_at is None]
            assert len(open_ids) == 2
        # 只退出一个终端，另一个终端仍保持在线
        resp = clients[0].post('/logout', data={'csrf_token': CSRF},
                               headers={'X-CSRFToken': CSRF},
                               follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        with app.app_context():
            closed = AccountSession.query.filter_by(
                account_type='student', account_id=ids['stu']).filter(
                    AccountSession.logout_at.isnot(None)).all()
            still_open = AccountSession.query.filter_by(
                account_type='student', account_id=ids['stu']).filter(
                    AccountSession.logout_at.is_(None)).all()
            assert len(closed) == 1 and len(still_open) == 1
            assert closed[0].logout_reason == 'logout'
            page_count = AccountPageView.query.filter_by(
                session_id=closed[0].id).count()
            assert page_count >= 1
        admin = _client(app, is_admin=True, admin_name='轨迹管理员')
        listing = admin.get(f'/admin/account-trail?q=__trail_stu_{sfx}')
        assert listing.status_code == 200
        text = listing.get_data(as_text=True)
        assert f'__trail_stu_{sfx}' in text and '账号轨迹' in text
        detail = admin.get(
            f'/admin/account-trail/{closed[0].id}')
        assert detail.status_code == 200
        assert '今日学习' in detail.get_data(as_text=True)
    finally:
        with app.app_context():
            session_ids = [row.id for row in AccountSession.query.filter_by(
                account_type='student', account_id=ids['stu']).all()]
            if session_ids:
                AccountPageView.query.filter(
                    AccountPageView.session_id.in_(session_ids)).delete(
                        synchronize_session=False)
                AccountSession.query.filter(
                    AccountSession.id.in_(session_ids)).delete(
                        synchronize_session=False)
            AttendanceRecord.query.filter_by(student_id=ids['stu']).delete(
                synchronize_session=False)
            ClassroomSession.query.filter_by(class_id=ids['cls']).delete(
                synchronize_session=False)
            Student.query.filter_by(id=ids['stu']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
            db.session.commit()
            cache.clear()


def test_admin_dashboard_shows_deployment_checks_and_steps(app):
    anon = app.test_client()
    assert anon.get('/admin/dashboard', follow_redirects=False).status_code in (
        301, 302, 303, 307, 308)
    admin = _client(app, is_admin=True, admin_name='总览管理员')
    page = admin.get('/admin/dashboard')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    for marker in ('管理总览', '部署检查清单', '首次使用步骤', '账号轨迹',
                   '数据与审计', '教师账号', '配置课程表（可选）',
                   '支持 Excel/文本批量导入', '可选'):
        assert marker in text
    assert '管理总览' in (ROOT / 'templates' / 'base.html').read_text(
        encoding='utf-8')


def test_student_import_template_has_grade_dropdown(app):
    admin = _client(app, is_admin=True, admin_name='导入模板管理员')
    response = admin.get('/admin/students/template')
    assert response.status_code == 200
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(response.data))
    assert '学生导入模板' in wb.sheetnames
    assert '年级选项' in wb.sheetnames
    ws = wb['学生导入模板']
    validations = list(ws.data_validations.dataValidation)
    assert any('年级选项' in (dv.formula1 or '') for dv in validations)


def test_account_trail_single_and_batch_delete(app):
    sfx = uuid.uuid4().hex[:8]
    with app.app_context():
        rows = []
        for i in range(2):
            sid = uuid.uuid4().hex
            rows.append(AccountSession(
                id=sid, account_type='student', account_id=9000 + i,
                account_name=f'__trail_del_{sfx}_{i}', channel='web',
                login_ip='127.0.0.1', page_count=1))
        db.session.add_all(rows)
        db.session.flush()
        for i, row in enumerate(rows):
            db.session.add(AccountPageView(
                session_id=row.id, account_type='student',
                account_id=9000 + i, endpoint='student_home.student_home',
                path='/student/home'))
        db.session.commit()
        session_ids = [row.id for row in rows]
    try:
        admin = _client(app, is_admin=True, admin_name='删除轨迹管理员')
        resp = admin.post(
            f'/admin/account-trail/{session_ids[0]}/delete',
            data={'csrf_token': CSRF,
                  'next': '/admin/account-trail?type=student'},
            headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        with app.app_context():
            assert db.session.get(AccountSession, session_ids[0]) is None
            assert AccountPageView.query.filter_by(
                session_id=session_ids[0]).count() == 0
            assert db.session.get(AccountSession, session_ids[1]) is not None
            assert Log.query.filter_by(action='删除账号轨迹').count() >= 1
        resp = admin.post(
            '/admin/account-trail/delete',
            data={'csrf_token': CSRF, 'session_ids': [session_ids[1]],
                  'next': '/admin/account-trail'},
            headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307, 308)
        with app.app_context():
            assert db.session.get(AccountSession, session_ids[1]) is None
            assert AccountPageView.query.filter_by(
                session_id=session_ids[1]).count() == 0
    finally:
        with app.app_context():
            AccountPageView.query.filter(
                AccountPageView.session_id.in_(session_ids)).delete(
                    synchronize_session=False)
            AccountSession.query.filter(
                AccountSession.id.in_(session_ids)).delete(
                    synchronize_session=False)
            Log.query.filter(Log.detail.contains(f'__trail_del_{sfx}')).delete(
                synchronize_session=False)
            db.session.commit()
