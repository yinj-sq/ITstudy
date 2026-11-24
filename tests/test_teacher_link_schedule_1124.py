# -*- coding: utf-8 -*-
"""教师编辑模式：外链资源与个人课程表（2026-11-24）。"""
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, ClassSchedule, Log, Resource, Schedule,
                        Subject, Teacher, teacher_class, teacher_subject)
from app.utils import invalidate_lookup_cache

CSRF = 't'


@pytest.fixture(scope='module')
def app():
    application = create_app()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def _teacher_client(app, teacher_id, mode='edit'):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(is_teacher=True, teacher_id=teacher_id,
                    teacher_name='外链/课表测试教师', teacher_mode=mode,
                    csrf_token=CSRF)
    return client


def _post(client, path, data):
    data = dict(data)
    data['csrf_token'] = CSRF
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def _make_teacher_class(app, suffix):
    with app.app_context():
        subject = Subject(name=f'外链学科_{suffix}')
        cls = Class(name=f'外链班级_{suffix}')
        teacher = Teacher(username=f'__ext_teacher_{suffix}',
                          display_name='外链测试教师')
        teacher.set_password('ExtPass123')
        db.session.add_all([subject, cls, teacher])
        db.session.flush()
        db.session.execute(teacher_subject.insert().values(
            teacher_id=teacher.id, subject_id=subject.id))
        db.session.execute(teacher_class.insert().values(
            teacher_id=teacher.id, class_id=cls.id))
        db.session.commit()
        return teacher.id, subject.id, cls.id


def _cleanup(app, teacher_id, subject_id, class_id):
    with app.app_context():
        Log.query.filter(Log.detail.like('%外链测试资源%')).delete(
            synchronize_session=False)
        cls = db.session.get(Class, class_id)
        if cls:
            ClassSchedule.query.filter_by(class_name=cls.name).delete(
                synchronize_session=False)
        db.session.execute(teacher_subject.delete().where(
            teacher_subject.c.teacher_id == teacher_id))
        db.session.execute(teacher_class.delete().where(
            teacher_class.c.teacher_id == teacher_id))
        Resource.query.filter_by(creator_teacher_id=teacher_id).delete(
            synchronize_session=False)
        Teacher.query.filter_by(id=teacher_id).delete(synchronize_session=False)
        Subject.query.filter_by(id=subject_id).delete(synchronize_session=False)
        Class.query.filter_by(id=class_id).delete(synchronize_session=False)
        db.session.commit()
        invalidate_lookup_cache('schedules')


def test_teacher_edit_mode_adds_external_link_resource(app):
    suffix = uuid.uuid4().hex[:8]
    teacher_id, subject_id, class_id = _make_teacher_class(app, suffix)
    title = f'外链测试资源_{suffix}'
    try:
        client = _teacher_client(app, teacher_id)
        response = _post(client, '/teacher/resource-library/add-link', {
            'title': title,
            'url': 'https://example.com/demo',
            'subject_id': str(subject_id),
        })
        assert response.status_code == 302
        with app.app_context():
            resource = Resource.query.filter_by(title=title).one()
            assert resource.url == 'https://example.com/demo'
            assert resource.creator_type == 'teacher'
            assert resource.creator_teacher_id == teacher_id
            assert resource.subject_id == subject_id
            assert resource.show_in_student and resource.show_in_classroom
    finally:
        _cleanup(app, teacher_id, subject_id, class_id)


def test_teacher_edit_mode_adds_and_deletes_own_schedule(app):
    suffix = uuid.uuid4().hex[:8]
    teacher_id, subject_id, class_id = _make_teacher_class(app, suffix)
    class_name = f'外链班级_{suffix}'
    with app.app_context():
        period = Schedule(period_name=f'外链节次_{suffix}',
                          start_time='08:00', end_time='08:45',
                          sort_order=999)
        db.session.add(period)
        db.session.commit()
        period_id = period.id
        invalidate_lookup_cache('schedules')
    try:
        client = _teacher_client(app, teacher_id)
        response = _post(client, '/teacher/schedule/add', {
            'weekday': '1',
            'period_number': '1',
            'class_name': class_name,
        })
        assert response.status_code == 302
        with app.app_context():
            entry = ClassSchedule.query.filter_by(
                weekday=1, period_number=1, class_name=class_name).one()
            entry_id = entry.id
        response = _post(
            client, f'/teacher/schedule/{entry_id}/delete', {})
        assert response.status_code == 302
        with app.app_context():
            assert db.session.get(ClassSchedule, entry_id) is None
    finally:
        with app.app_context():
            Schedule.query.filter_by(id=period_id).delete(
                synchronize_session=False)
            db.session.commit()
        _cleanup(app, teacher_id, subject_id, class_id)


def test_teacher_cannot_add_link_for_foreign_subject(app):
    suffix = uuid.uuid4().hex[:8]
    teacher_id, subject_id, class_id = _make_teacher_class(app, suffix)
    with app.app_context():
        foreign = Subject(name=f'外学科_{suffix}')
        db.session.add(foreign)
        db.session.commit()
        foreign_id = foreign.id
    try:
        client = _teacher_client(app, teacher_id)
        _post(client, '/teacher/resource-library/add-link', {
            'title': f'外链测试资源_{suffix}',
            'url': 'https://example.com/demo',
            'subject_id': str(foreign_id),
        })
        with app.app_context():
            assert Resource.query.filter_by(
                creator_teacher_id=teacher_id).count() == 0
    finally:
        with app.app_context():
            Subject.query.filter_by(id=foreign_id).delete(
                synchronize_session=False)
            db.session.commit()
        _cleanup(app, teacher_id, subject_id, class_id)
