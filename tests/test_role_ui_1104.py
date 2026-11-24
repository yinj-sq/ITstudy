# -*- coding: utf-8 -*-
"""教师上传页学科权限与 /study 清空筛选按钮回归（2026-11-04）。

- 教师上传资源页不应出现「添加学科」入口（后端 add_subject 仅管理员）；
  管理员上传页保留；教师页给出“学科由管理员维护”的提示。
- /study 搜索框旁的「✕」是清空搜索/学科筛选按钮：仅在有搜索词或学科
  筛选时显示；无筛选时不显示（学生、教师同模板）。
"""
import re
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import Resource, Subject, SystemConfig, Teacher, teacher_subject

CSRF = 'role-ui-csrf'
CLEAR_TITLE = '清空搜索'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_teacher_upload_hides_subject_creation(app):
    sfx = uuid.uuid4().hex[:8]
    created_subject = None
    try:
        with app.app_context():
            teacher = Teacher(username=f'__rui_t_{sfx}',
                              display_name='学科界面教师')
            teacher.set_password('pass123456')
            db.session.add(teacher)
            subject = Subject.query.first()
            if not subject:
                subject = Subject(name=f'__rui_sub_{sfx}', sort_order=99)
                db.session.add(subject)
                created_subject = subject.name
            db.session.flush()
            db.session.execute(teacher_subject.insert().values(
                teacher_id=teacher.id, subject_id=subject.id))
            db.session.commit()
            tid = teacher.id
        teacher_client = _client(app, is_teacher=True, teacher_id=tid,
                                 teacher_name='学科界面教师',
                                 teacher_mode='edit')
        page = teacher_client.get('/teacher/resource-library/upload')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '添加学科' not in text
        assert 'subjectModal' not in text
        assert '/admin/subjects' not in text
        assert '学科由管理员统一维护' in text
        # 管理员上传页仍保留
        admin = _client(app, is_admin=True, admin_name='管理员')
        page = admin.get('/admin/resources/upload_page')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '添加学科' in text and 'subjectModal' in text
        # 学科学科筛选清空按钮对照：管理员资源页没有该搜索区
        page = admin.get('/admin/resources')
        assert CLEAR_TITLE not in page.get_data(as_text=True)
    finally:
        with app.app_context():
            teacher = Teacher.query.filter_by(
                username=f'__rui_t_{sfx}').first()
            if teacher:
                db.session.execute(teacher_subject.delete().where(
                    teacher_subject.c.teacher_id == teacher.id))
                Teacher.query.filter_by(id=teacher.id).delete(
                    synchronize_session=False)
            if created_subject:
                Subject.query.filter_by(name=created_subject).delete(
                    synchronize_session=False)
            db.session.commit()


def test_study_clear_button_only_with_active_filter(app):
    """搜索框旁的 ✕ 只在有搜索词时显示；学科切换本身不显示。

    切换学科后用户仍可用左侧「全部资源」回到未筛选状态，搜索框旁的
    ✕ 只负责清搜索词，并保留当前学科与课堂模式。
    """
    with app.app_context():
        old_public = SystemConfig.get('courseware_public_enabled')
    try:
        with app.app_context():
            SystemConfig.set('courseware_public_enabled', '1')
            subject = Subject.query.first()
            db.session.commit()
            sid = subject.id if subject else None
        anon = app.test_client()
        page = anon.get('/study')
        assert page.status_code == 200
        assert CLEAR_TITLE not in page.get_data(as_text=True)

        page = anon.get('/study?q=测试')
        text = page.get_data(as_text=True)
        assert CLEAR_TITLE in text
        m = re.search(r'href="([^"]+)"[^>]*title="' + CLEAR_TITLE + '"', text)
        assert m, '未找到清空搜索链接'
        href = m.group(1)
        assert 'q=' not in href and 'subject=' not in href

        if sid:
            # 仅切换学科：不出现搜索清空按钮
            page = anon.get(f'/study?subject={sid}')
            text = page.get_data(as_text=True)
            assert CLEAR_TITLE not in text
            # 搜索词 + 学科：清空搜索保留学科
            page = anon.get(f'/study?subject={sid}&q=测试')
            text = page.get_data(as_text=True)
            assert CLEAR_TITLE in text
            m = re.search(
                r'href="([^"]+)"[^>]*title="' + CLEAR_TITLE + '"', text)
            href = m.group(1) if m else ''
            assert f'subject={sid}' in href and 'q=' not in href

        # 课堂模式的清空链接需保留 mode=classroom
        admin = _client(app, is_admin=True, admin_name='管理员')
        page = admin.get('/study?mode=classroom&q=测试')
        text = page.get_data(as_text=True)
        assert CLEAR_TITLE in text
        m = re.search(r'href="([^"]+)"[^>]*title="' + CLEAR_TITLE + '"', text)
        href = m.group(1) if m else ''
        assert 'mode=classroom' in href
        assert 'q=' not in href
    finally:
        with app.app_context():
            if old_public is None:
                SystemConfig.set('courseware_public_enabled', '1')
            else:
                SystemConfig.set('courseware_public_enabled', old_public)
            db.session.commit()


def test_classroom_lesson_clock_and_exit_button(app):
    """课堂模式左侧栏显示课堂时钟与退出按钮；普通浏览模式不显示。"""
    sfx = uuid.uuid4().hex[:8]
    tid = rid = None
    try:
        with app.app_context():
            teacher = Teacher(username=f'__rui_clock_{sfx}',
                              display_name='课堂时钟教师')
            teacher.set_password('pass123456')
            db.session.add(teacher)
            db.session.flush()
            res = Resource(
                title=f'__rui_clock_res_{sfx}',
                show_in_student=True, show_in_classroom=True,
                creator_type='teacher', creator_teacher_id=teacher.id,
                creator_name='课堂时钟教师', quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            tid, rid = teacher.id, res.id

        teacher_client = _client(app, is_teacher=True, teacher_id=tid,
                                 teacher_name='课堂时钟教师',
                                 teacher_mode='edit')
        text = teacher_client.get(
            f'/study/lesson/{rid}?mode=classroom').get_data(as_text=True)
        assert 'id="lessonClockTime"' in text
        assert 'id="lessonClockDate"' in text
        assert '退出课堂模式' in text
        assert 'href="/study?mode=classroom"' in text
        # 时钟位于章节树之前（侧栏课程内容上方）
        assert text.index('lessonClock') < text.index('chapterTree')

        plain = teacher_client.get(f'/study/lesson/{rid}').get_data(as_text=True)
        assert 'id="lessonClockTime"' not in plain
        assert '退出课堂模式' not in plain
    finally:
        with app.app_context():
            if rid:
                Resource.query.filter_by(id=rid).delete(
                    synchronize_session=False)
            if tid:
                Teacher.query.filter_by(id=tid).delete(
                    synchronize_session=False)
            db.session.commit()
