# -*- coding: utf-8 -*-
"""教师年级/班级范围：作业管理与数据统计回归（2026-10-22）。"""
import pathlib
import uuid

from app import create_app
from app.extensions import db
from app.models import (Class, Homework, Student, Subject, Teacher,
                        teacher_class, teacher_subject)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSRF = 't'


def test_teacher_homework_and_statistics_are_class_scoped():
    suffix = uuid.uuid4().hex[:8]
    c1_name = f'__scope_A_{suffix}'
    c2_name = f'__scope_B_{suffix}'
    username = f'__scope_teacher_{suffix}'
    subj_name = f'__scope_subject_{suffix}'
    hw_a = f'__scope_hw_A_{suffix}'
    hw_b = f'__scope_hw_B_{suffix}'
    app = create_app()
    try:
        with app.app_context():
            c1 = Class(name=c1_name, description='教师任课班')
            c2 = Class(name=c2_name, description='非任课班')
            subj = Subject(name=subj_name, sort_order=915)
            teacher = Teacher(username=username, display_name='班级范围教师', grade='高一')
            teacher.set_password('pass123456')
            teacher.subjects = [subj]
            teacher.classes = [c1]
            db.session.add_all([c1, c2, subj, teacher])
            db.session.flush()
            s1 = Student(name='范围学生A', student_number=f'__scope_stu_{suffix}',
                         student_class=c1_name, class_id=c1.id, has_changed_password=True)
            s1.set_password('x')
            db.session.add(s1)
            h1 = Homework(title=hw_a, teacher_id=teacher.id, is_active=True)
            h2 = Homework(title=hw_b, teacher_id=teacher.id, is_active=True)
            h1.classes.append(c1)
            h2.classes.append(c2)
            db.session.add_all([h1, h2])
            db.session.commit()
            tid, c2id = teacher.id, c2.id
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['is_teacher'] = True
            sess['teacher_id'] = tid
            sess['teacher_name'] = '班级范围教师'
            sess['teacher_mode'] = 'edit'
            sess['csrf_token'] = CSRF
        home = client.get('/admin/homework').get_data(as_text=True)
        assert hw_a in home and hw_b not in home
        stats = client.get('/admin/statistics')
        assert stats.status_code == 200
        stats_html = stats.get_data(as_text=True)
        assert c1_name in stats_html and c2_name not in stats_html
        # 不能给非任课班级发布作业
        resp = client.post('/admin/homework/create', data={
            'csrf_token': CSRF, 'title': f'__scope_bad_{suffix}',
            'class_ids': [str(c2id)], 'subject_id': '',
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 302
        with app.app_context():
            assert Homework.query.filter_by(title=f'__scope_bad_{suffix}').count() == 0
    finally:
        with app.app_context():
            for title in (hw_a, hw_b, f'__scope_bad_{suffix}'):
                hw = Homework.query.filter_by(title=title).first()
                if hw:
                    hw.classes = []
                    db.session.delete(hw)
            db.session.commit()
            Student.query.filter(Student.student_number == f'__scope_stu_{suffix}').delete(
                synchronize_session=False)
            db.session.execute(teacher_class.delete())
            db.session.execute(teacher_subject.delete())
            Teacher.query.filter_by(username=username).delete(synchronize_session=False)
            Subject.query.filter_by(name=subj_name).delete(synchronize_session=False)
            Class.query.filter(Class.name.in_([c1_name, c2_name])).delete(
                synchronize_session=False)
            db.session.commit()
