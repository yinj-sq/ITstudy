# -*- coding: utf-8 -*-
"""作业停用后历史查看与学生附件删除回归（2026-10-23）。"""
import json
import os
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, Homework, HomeworkSubmission, Student
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


def test_closed_homework_history_visible_and_attachment_delete(app):
    sfx = uuid.uuid4().hex[:8]
    class_name = f'__closed_hw_cls_{sfx}'
    number = f'__closed_hw_stu_{sfx}'
    hw_title = f'__closed_hw_{sfx}'
    sub_id = hw_id = None
    sub_dir = None
    try:
        with app.app_context():
            cls = Class(name=class_name)
            stu = Student(name='停课作业学生', student_number=number,
                          student_class=class_name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, stu])
            db.session.flush()
            stu.class_id = cls.id
            hw = Homework(title=hw_title, is_active=True, teacher_id=None)
            hw.classes.append(cls)
            db.session.add(hw)
            db.session.flush()
            sub = HomeworkSubmission(
                homework_id=hw.id, student_id=stu.id, text_content='历史答案',
                grade='A', status='graded',
                files=json.dumps(['a.txt', 'b.txt']))
            db.session.add(sub)
            db.session.commit()
            hw_id, sub_id = hw.id, sub.id
            stu_id = stu.id
            sub_dir = os.path.join(SUBMISSION_DIR, str(sub.id))
            os.makedirs(sub_dir, exist_ok=True)
            for name in ('a.txt', 'b.txt'):
                with open(os.path.join(sub_dir, name), 'wb') as f:
                    f.write(name.encode())

        student = _client(app, student_id=stu_id, student_name='停课作业学生',
                          has_changed_password=True)
        # 先确认停用前可以提交/删除
        assert student.get(f'/student/homework/{hw_id}').status_code == 200
        with app.app_context():
            hw = db.session.get(Homework, hw_id)
            hw.is_active = False
            db.session.commit()

        # 停用后仍出现在列表，详情只读，结果仍可查看
        listing = student.get('/student/homework').get_data(as_text=True)
        assert hw_title in listing and '已关闭' in listing
        detail = student.get(f'/student/homework/{hw_id}')
        assert detail.status_code == 200
        assert '作业已关闭' in detail.get_data(as_text=True)
        assert '提交作业' not in detail.get_data(as_text=True)
        result = student.get(f'/student/homework/{hw_id}/result')
        assert result.status_code == 200
        assert '历史答案' in result.get_data(as_text=True)
        assert 'A' in result.get_data(as_text=True)
        # 自己的附件在停用后仍可预览
        assert student.get(
            f'/student/homework/preview-submission/{sub_id}/a.txt').status_code == 200
        # 停用后 POST 仍被拒绝
        resp = student.post(f'/student/homework/{hw_id}', data={
            'csrf_token': CSRF, 'text_content': '不应写入',
        }, headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert resp.status_code in (301, 302)
        with app.app_context():
            assert db.session.get(HomeworkSubmission, sub_id).text_content == '历史答案'

        # 重新启用后，删除旧附件并可被记录移除
        with app.app_context():
            hw = db.session.get(Homework, hw_id)
            hw.is_active = True
            db.session.commit()
        resp = student.post(
            f'/student/homework/{hw_id}/submission/{sub_id}/files/delete',
            data={'csrf_token': CSRF, 'filename': 'a.txt'},
            headers={'X-CSRFToken': CSRF}, follow_redirects=False)
        assert resp.status_code in (301, 302)
        with app.app_context():
            sub = db.session.get(HomeworkSubmission, sub_id)
            assert json.loads(sub.files) == ['b.txt']
            assert sub.status == 'submitted' and sub.grade is None
        assert not os.path.exists(os.path.join(sub_dir, 'a.txt'))
        assert os.path.exists(os.path.join(sub_dir, 'b.txt'))
    finally:
        with app.app_context():
            if sub_id:
                HomeworkSubmission.query.filter_by(id=sub_id).delete(
                    synchronize_session=False)
            if hw_id:
                hw = db.session.get(Homework, hw_id)
                if hw:
                    hw.classes = []
                    db.session.delete(hw)
            Student.query.filter_by(student_number=number).delete(
                synchronize_session=False)
            Class.query.filter_by(name=class_name).delete(synchronize_session=False)
            db.session.commit()
        if sub_dir:
            import shutil
            shutil.rmtree(sub_dir, ignore_errors=True)
