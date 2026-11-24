"""作业重交附件合并回归测试（此前缺陷：重交整体替换附件集合并删旧文件）

场景：首次提交 2 个附件 → 重交补传 1 个 → 旧附件必须保留（共 3 个），
磁盘目录与提交记录一致，不产生附件永久丢失。
"""
import io
import json
import os
import shutil

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, Student, Homework, HomeworkSubmission, homework_classes

_CSRF = 'test-csrf-token'
_SUBMISSION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'submissions')


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        db.session.rollback()
        db.session.execute(db.text(
            'TRUNCATE homework_submission, homework_classes, homework, '
            'classes, student RESTART IDENTITY CASCADE'))
        db.session.commit()


def _setup(app):
    """创建 班级 → 学生 → 作业(该班级) → 返回 (cls_id, stu_id, hw_id, sub_dir)"""
    with app.app_context():
        cls = Class(name='回归班级HW')
        db.session.add(cls)
        db.session.commit()
        cls_id = cls.id
        stu = Student(name='重交学生', student_number='HW-1', class_id=cls_id,
                      student_class='回归班级HW')
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        stu_id = stu.id
        hw = Homework(title='回归作业HW', is_active=True, teacher_id=None)
        hw.classes.append(cls)
        db.session.add(hw)
        db.session.commit()
        return cls_id, stu_id, hw.id


def _submit(client, hw_id, files):
    """以 multipart 表单提交作业。files: [(内容 bytes, 文件名), ...]"""
    data = {'text_content': '说明文本'}
    if files:
        data['files'] = [(io.BytesIO(content), fname) for content, fname in files]
    return client.post(f'/student/homework/{hw_id}',
                       data=data,
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': _CSRF},
                       follow_redirects=True)


def _login(app, stu_id):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['student_id'] = stu_id
        sess['student_name'] = '重交学生'
        sess['student_class_id'] = None
        sess['csrf_token'] = _CSRF
        sess.permanent = True
    return client


def test_resubmit_merges_old_attachments(app):
    cls_id, stu_id, hw_id = _setup(app)
    client = _login(app, stu_id)
    try:
        # 首次提交 2 个附件
        resp = _submit(client, hw_id, [(b'content-a', 'a.txt'), (b'content-b', 'b.txt')])
        assert resp.status_code == 200
        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw_id, student_id=stu_id).first()
            assert sub is not None
            first_files = json.loads(sub.files)
            assert sorted(first_files) == ['a.txt', 'b.txt'], first_files

        # 重交补传 1 个新附件（不再上传 a.txt/b.txt）
        resp = _submit(client, hw_id, [(b'content-c', 'c.txt')])
        assert resp.status_code == 200

        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw_id, student_id=stu_id).first()
            merged = json.loads(sub.files)
            # 核心断言：旧附件必须保留,与本次新附件合并
            assert sorted(merged) == ['a.txt', 'b.txt', 'c.txt'], merged
            # 磁盘与记录一致：目录下正好 3 个文件且内容完整
            sub_dir = os.path.join(_SUBMISSION_DIR, str(sub.id))
            on_disk = sorted(os.listdir(sub_dir)) if os.path.isdir(sub_dir) else []
            assert sorted(on_disk) == sorted(merged), on_disk
            with open(os.path.join(sub_dir, 'a.txt'), 'rb') as f:
                assert f.read() == b'content-a'

        # 同名重传去重：再交一次 a.txt 不应产生重复条目
        resp = _submit(client, hw_id, [(b'content-a2', 'a.txt')])
        assert resp.status_code == 200
        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw_id, student_id=stu_id).first()
            merged2 = json.loads(sub.files)
            assert merged2.count('a.txt') == 1
            assert sorted(merged2) == ['a.txt', 'b.txt', 'c.txt']
    finally:
        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw_id, student_id=stu_id).first()
            sub_dir = None
            if sub:
                sub_dir = os.path.join(_SUBMISSION_DIR, str(sub.id))
                db.session.delete(sub)
            db.session.execute(homework_classes.delete().where(
                homework_classes.c.homework_id == hw_id))
            Homework.query.filter_by(id=hw_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
            db.session.commit()
            if sub_dir and os.path.isdir(sub_dir):
                shutil.rmtree(sub_dir, ignore_errors=True)
