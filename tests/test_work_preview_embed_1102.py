# -*- coding: utf-8 -*-
"""作品预览返回路径与评价页内嵌预览回归（2026-11-02）。

修复点：
- 作品列表“预览”打开后，“返回”回到作品列表（保留分页），不再跳到学生活动页；
- 评价页作品文件自动内嵌在“作品内容”框中，带缩放控件，不再新开标签页；
- 评价来源的预览页“返回”回到评价页；学生端仍只能回到学生活动页。
"""
import pathlib
import shutil
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, LearningActivity, Resource, Student,
                        StudentWork, Teacher, teacher_class)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'work-preview-embed-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_work_preview_embed_and_back_paths(app):
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__work_preview_{sfx}'
    target = UPLOADS / dir_name
    ids = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'answer.txt').write_text('学生作品预览内容', encoding='utf-8')

        with app.app_context():
            cls = Class(name=f'__wp_cls_{sfx}')
            teacher = Teacher(username=f'__wp_t_{sfx}', display_name='预览教师')
            teacher.set_password('pass123456')
            teacher.classes.append(cls)
            stu = Student(name='预览学生', student_number=f'__wp_s_{sfx}',
                          student_class=cls.name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, teacher, stu])
            db.session.flush()
            stu.class_id = cls.id
            res = Resource(title=f'__wp_res_{sfx}', url='',
                           show_in_student=True, show_in_classroom=True,
                           creator_type='teacher', creator_teacher_id=teacher.id,
                           creator_name=teacher.display_name)
            db.session.add(res)
            db.session.flush()
            act = LearningActivity(resource_id=res.id, title=f'__wp_act_{sfx}',
                                   require_upload=True, is_active=True)
            db.session.add(act)
            db.session.flush()
            work = StudentWork(
                activity_id=act.id, student_id=stu.id, status='submitted',
                original_filename='answer.txt',
                file_path=f'{dir_name}/answer.txt', file_size=24,
            )
            db.session.add(work)
            db.session.commit()
            ids = {'cls': cls.id, 'teacher': teacher.id, 'stu': stu.id,
                   'res': res.id, 'act': act.id, 'work': work.id}

        teacher_client = _client(
            app, is_teacher=True, teacher_id=ids['teacher'],
            teacher_name='预览教师', teacher_mode='edit')

        # 评价页：文件预览自动内嵌，带缩放控件，不再有单独“预览作品文件”按钮
        evaluate_html = teacher_client.get(
            f'/teacher/works/evaluate/{ids["work"]}').get_data(as_text=True)
        assert 'id="workPreviewFrame"' in evaluate_html
        assert 'embed=1' in evaluate_html and 'source=evaluate' in evaluate_html
        assert 'workPreviewZoomIn' in evaluate_html
        assert 'workPreviewZoomOut' in evaluate_html
        assert 'workPreviewZoomReset' in evaluate_html
        assert '预览作品文件' not in evaluate_html

        # 作品列表：预览链接带 source=works 与当前页，返回可回列表
        list_html = teacher_client.get(
            f'/teacher/works/activity/{ids["act"]}').get_data(as_text=True)
        assert 'source=works' in list_html

        # 预览页返回路径按来源区分
        eval_preview = teacher_client.get(
            f'/works/file/{ids["work"]}/preview?embed=1&source=evaluate').get_data(
            as_text=True)
        assert '返回评价页' in eval_preview
        assert f'/teacher/works/evaluate/{ids["work"]}' in eval_preview

        works_preview = teacher_client.get(
            f'/works/file/{ids["work"]}/preview?source=works&page=2').get_data(
            as_text=True)
        assert '返回作品列表' in works_preview
        assert f'/teacher/works/activity/{ids["act"]}' in works_preview
        assert 'page=2' in works_preview

        student_only = teacher_client.get(
            f'/works/file/{ids["work"]}/preview').get_data(as_text=True)
        assert '返回活动' in student_only
        assert f'/study/activity/{ids["act"]}' in student_only

        # 学生端即使手工带 source=works，也只能回学生活动页（不泄露教师页面）
        stu_client = _client(app, student_id=ids['stu'], student_name='预览学生',
                             has_changed_password=True)
        stu_preview = stu_client.get(
            f'/works/file/{ids["work"]}/preview?source=works').get_data(as_text=True)
        assert '返回活动' in stu_preview
        assert f'/study/activity/{ids["act"]}' in stu_preview
        assert '/teacher/works/activity/' not in stu_preview
    finally:
        with app.app_context():
            if ids.get('work'):
                StudentWork.query.filter_by(id=ids['work']).delete(
                    synchronize_session=False)
            if ids.get('act'):
                LearningActivity.query.filter_by(id=ids['act']).delete(
                    synchronize_session=False)
            if ids.get('res'):
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            if ids.get('teacher'):
                db.session.execute(teacher_class.delete().where(
                    teacher_class.c.teacher_id == ids['teacher']))
                Teacher.query.filter_by(id=ids['teacher']).delete(
                    synchronize_session=False)
            if ids.get('stu'):
                Student.query.filter_by(id=ids['stu']).delete(
                    synchronize_session=False)
            if ids.get('cls'):
                Class.query.filter_by(id=ids['cls']).delete(
                    synchronize_session=False)
            db.session.commit()
        shutil.rmtree(target, ignore_errors=True)
