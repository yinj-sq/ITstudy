# -*- coding: utf-8 -*-
"""教师资源库成绩入口与资源所有权边界回归（2026-10-23）。"""
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, Resource, ResourceQuizResult, Student, Teacher

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


def test_teacher_quiz_results_owner_access_and_library_entry(app):
    sfx = uuid.uuid4().hex[:8]
    cls_name = f'__quiz_cls_{sfx}'
    owner_name = f'__quiz_owner_{sfx}'
    other_name = f'__quiz_other_{sfx}'
    stu_num = f'__quiz_stu_{sfx}'
    res_title = f'__quiz_res_{sfx}'
    quiz_name = f'__quiz_name_{sfx}'
    rid = tid = oid = rqid = None
    try:
        with app.app_context():
            cls = Class(name=cls_name)
            owner = Teacher(username=owner_name, display_name='成绩资源教师')
            owner.set_password('pass123456')
            other = Teacher(username=other_name, display_name='其他教师')
            other.set_password('pass123456')
            db.session.add_all([cls, owner, other])
            db.session.flush()
            owner.classes = [cls]
            stu = Student(name='成绩学生', student_number=stu_num,
                          student_class=cls_name, class_id=cls.id,
                          has_changed_password=True)
            stu.set_password('pass123456')
            res = Resource(title=res_title, show_in_student=True,
                           show_in_classroom=True, quiz_mode='inject',
                           creator_type='teacher', creator_teacher_id=owner.id,
                           creator_name=owner.display_name)
            db.session.add_all([stu, res])
            db.session.flush()
            result = ResourceQuizResult(
                student_id=stu.id, resource_id=res.id, quiz_name=quiz_name,
                answers='{"q1":"A"}', scores='{"q1":10}',
                total_score=10, max_score=10, grade='优秀')
            db.session.add(result)
            db.session.commit()
            rid, tid, oid, rqid = res.id, owner.id, other.id, result.id

        owner_client = _client(app, is_teacher=True, teacher_id=tid,
                               teacher_name='成绩资源教师', teacher_mode='edit')
        library = owner_client.get('/teacher/resource-library').get_data(as_text=True)
        assert f'/admin/resources/quiz_results/{rid}' in library
        page = owner_client.get(f'/admin/resources/quiz_results/{rid}')
        assert page.status_code == 200
        assert quiz_name in page.get_data(as_text=True)
        assert owner_client.get(f'/api/results/quiz/{rqid}').status_code == 200
        assert owner_client.get(
            f'/admin/resources/quiz_results_data/{rid}').status_code == 200

        other_client = _client(app, is_teacher=True, teacher_id=oid,
                               teacher_name='其他教师', teacher_mode='edit')
        assert other_client.get(
            f'/admin/resources/quiz_results/{rid}').status_code == 403
        assert other_client.get(
            f'/api/results/quiz/{rqid}').status_code == 403

        admin = _client(app, is_admin=True, admin_name='管理员')
        assert admin.get(f'/admin/resources/quiz_results/{rid}').status_code == 200
        assert admin.get(f'/api/results/quiz/{rqid}').status_code == 200
    finally:
        with app.app_context():
            if rqid is not None:
                ResourceQuizResult.query.filter_by(id=rqid).delete(
                    synchronize_session=False)
            if rid is not None:
                Resource.query.filter_by(id=rid).delete(synchronize_session=False)
            Student.query.filter_by(student_number=stu_num).delete(
                synchronize_session=False)
            db.session.execute(db.text(
                'DELETE FROM teacher_class WHERE teacher_id IN '
                '(SELECT id FROM teacher WHERE username IN (:a, :b))'
            ), {'a': owner_name, 'b': other_name})
            Teacher.query.filter(Teacher.username.in_(
                [owner_name, other_name])).delete(synchronize_session=False)
            Class.query.filter_by(name=cls_name).delete(synchronize_session=False)
            db.session.commit()
