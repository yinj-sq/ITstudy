# -*- coding: utf-8 -*-
"""教师端作业提交的班级边界回归（2026-10-23）。

管理员可将一份作业同时发给多个班。教师只能看到/批改/预览/导出本人任课
班级学生的提交；此前列表与批改动作仅按 homework_id 过滤，会横向暴露其他班。
"""
import io
import json
import os
import uuid
import zipfile

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, Homework, HomeworkSubmission, Student, Teacher
from app.blueprints.homework import SUBMISSION_DIR

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


def test_teacher_homework_submissions_are_class_scoped(app):
    sfx = uuid.uuid4().hex[:8]
    c1_name = f'__hw_scope_A_{sfx}'
    c2_name = f'__hw_scope_B_{sfx}'
    t_name = f'__hw_scope_t_{sfx}'
    s1_num = f'__hw_scope_s1_{sfx}'
    s2_num = f'__hw_scope_s2_{sfx}'
    hw_title = f'__hw_scope_hw_{sfx}'
    hw_id = t_id = None
    sub_ids = []
    try:
        with app.app_context():
            c1 = Class(name=c1_name)
            c2 = Class(name=c2_name)
            teacher = Teacher(username=t_name, display_name='作业边界教师')
            teacher.set_password('pass123456')
            db.session.add_all([c1, c2, teacher])
            db.session.flush()
            teacher.classes = [c1]
            stu1 = Student(name='边界学生甲', student_number=s1_num,
                           student_class=c1_name, class_id=c1.id,
                           has_changed_password=True)
            stu1.set_password('pass123456')
            stu2 = Student(name='边界学生乙', student_number=s2_num,
                           student_class=c2_name, class_id=c2.id,
                           has_changed_password=True)
            stu2.set_password('pass123456')
            db.session.add_all([stu1, stu2])
            db.session.flush()
            hw = Homework(title=hw_title, teacher_id=None, is_active=True)
            hw.classes.extend([c1, c2])
            db.session.add(hw)
            db.session.flush()
            sub1 = HomeworkSubmission(
                homework_id=hw.id, student_id=stu1.id, grade='A',
                status='graded', text_content='甲班提交',
                files=json.dumps(['a.txt']))
            sub2 = HomeworkSubmission(
                homework_id=hw.id, student_id=stu2.id, grade='A',
                status='graded', text_content='乙班提交',
                files=json.dumps(['b.txt']))
            db.session.add_all([sub1, sub2])
            db.session.commit()
            hw_id, t_id = hw.id, teacher.id
            sub_ids = [sub1.id, sub2.id]
            for sid, fn, content in ((sub1.id, 'a.txt', b'A file'),
                                     (sub2.id, 'b.txt', b'B file')):
                d = os.path.join(SUBMISSION_DIR, str(sid))
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, fn), 'wb') as f:
                    f.write(content)

        teacher_client = _client(app, is_teacher=True, teacher_id=t_id,
                                 teacher_name='作业边界教师',
                                 teacher_mode='edit')
        html = teacher_client.get(
            f'/admin/homework/{hw_id}/submissions').get_data(as_text=True)
        assert '边界学生甲' in html
        assert '边界学生乙' not in html
        assert c1_name in html and c2_name not in html
        html_b = teacher_client.get(
            f'/admin/homework/{hw_id}/submissions?class_id='
            f'{class_id_for(app, c2_name)}').get_data(as_text=True)
        assert '边界学生乙' not in html_b

        # 批改、附件预览、优秀作业导出都不能越过班级边界
        assert teacher_client.get(
            f'/admin/homework/{hw_id}/grade/{sub_ids[1]}',
            follow_redirects=False).status_code == 302
        assert teacher_client.get(
            f'/admin/homework/preview-submission/{sub_ids[1]}/b.txt').status_code == 403
        assert teacher_client.get(
            f'/admin/homework/preview-submission/{sub_ids[0]}/a.txt').status_code == 200
        export = teacher_client.get(f'/admin/homework/{hw_id}/export_excellent')
        assert export.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(export.data)).namelist()
        assert any('边界学生甲' in n for n in names)
        assert not any('边界学生乙' in n for n in names)

        # 管理员创建的多班作业，任课教师不能编辑/删除整份作业
        assert f'/admin/homework/{hw_id}/edit' not in teacher_client.get(
            '/admin/homework').get_data(as_text=True)
        assert teacher_client.get(
            f'/admin/homework/{hw_id}/edit',
            follow_redirects=False).status_code == 302
        assert teacher_client.post(
            f'/admin/homework/{hw_id}/delete',
            data={'csrf_token': CSRF},
            headers={'X-CSRFToken': CSRF},
            follow_redirects=False).status_code == 302
        with app.app_context():
            assert db.session.get(Homework, hw_id) is not None

        # 管理员不受班级边界影响，且可编辑/删除管理员创建的作业
        admin = _client(app, is_admin=True, admin_name='管理员')
        assert admin.get(f'/admin/homework/{hw_id}/edit').status_code == 200
        admin_html = admin.get(
            f'/admin/homework/{hw_id}/submissions').get_data(as_text=True)
        assert '边界学生甲' in admin_html and '边界学生乙' in admin_html
    finally:
        with app.app_context():
            if hw_id:
                subs = HomeworkSubmission.query.filter_by(homework_id=hw_id).all()
                for sub in subs:
                    path = os.path.join(SUBMISSION_DIR, str(sub.id))
                    if os.path.isdir(path):
                        import shutil
                        shutil.rmtree(path, ignore_errors=True)
                    db.session.delete(sub)
                hw = db.session.get(Homework, hw_id)
                if hw:
                    hw.classes = []
                    db.session.delete(hw)
            db.session.execute(db.text(
                'DELETE FROM teacher_class WHERE teacher_id IN '
                '(SELECT id FROM teacher WHERE username = :u)'), {'u': t_name})
            Teacher.query.filter_by(username=t_name).delete(synchronize_session=False)
            Student.query.filter(Student.student_number.in_(
                [s1_num, s2_num])).delete(synchronize_session=False)
            Class.query.filter(Class.name.in_([c1_name, c2_name])).delete(
                synchronize_session=False)
            db.session.commit()


def class_id_for(app, name):
    with app.app_context():
        cls = Class.query.filter_by(name=name).first()
        return cls.id if cls else 0
