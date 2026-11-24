# -*- coding: utf-8 -*-
"""教师教学台：按教学任务组织首页（课堂、资源、学生、实验）。"""
from datetime import datetime

from flask import Blueprint, render_template, session

from app.decorators import teacher_login_required
from app.extensions import db
from app.models import ClassSchedule, ClassroomSession, Resource, Teacher
from app.services.resource_access import teacher_classes
from app.utils import get_schedules_cached

teacher_home_bp = Blueprint('teacher_home', __name__, url_prefix='')


@teacher_home_bp.route('/teacher/dashboard')
@teacher_login_required
def teacher_dashboard():
    teacher_id = session.get('teacher_id')
    teacher = db.session.get(Teacher, teacher_id) if teacher_id else None
    classes = teacher_classes(teacher_id) if teacher_id else []
    class_ids = [c.id for c in classes]
    class_names = {c.name for c in classes}
    schedules = get_schedules_cached()
    now = datetime.now()
    weekday = now.weekday() + 1
    current_time = now.strftime('%H:%M')
    current_period = next(
        (s for s in schedules if s.start_time <= current_time <= s.end_time),
        None)
    today_entries = []
    if class_names:
        today_entries = ClassSchedule.query.filter(
            ClassSchedule.class_name.in_(class_names),
            ClassSchedule.weekday == weekday,
        ).order_by(ClassSchedule.period_number).all()
    active_sessions = []
    if class_ids:
        active_sessions = ClassroomSession.query.filter(
            ClassroomSession.class_id.in_(class_ids),
            ClassroomSession.is_active.is_(True)).all()
    resource_count = 0
    if teacher_id:
        resource_count = Resource.query.filter_by(
            creator_teacher_id=teacher_id).count()
    return render_template(
        'teacher_dashboard.html', teacher=teacher, classes=classes,
        today_entries=today_entries, current_period=current_period,
        active_sessions=active_sessions, resource_count=resource_count,
        readonly=session.get('teacher_mode') == 'readonly',
        weekday_name=ClassSchedule.WEEKDAY_NAMES.get(weekday, ''))
