import json
from datetime import datetime, timedelta
import threading

from flask import Blueprint, redirect, url_for, flash, session, render_template, request, abort

from app.extensions import db
from app.models import (Resource, TeachingSession, ClassroomSetting,
                        ClassroomSession, Class, Student, SystemConfig)
from app.decorators import teacher_login_required
from app.blueprints.auth import invalidate_active_class_cache
from app.utils import parse_int, sse_bump


teaching_bp = Blueprint('teaching', __name__, url_prefix='')

# 上课/下课查重-写入串行化锁：check-then-insert 在并发（教师双击、
# 双标签页同时提交）下可产生重复"进行中"记录，end_class 只收最新一条，
# 更早的记录永远 end_time=NULL。单实例 waitress 部署下进程内锁足够；
# 理论上 PG 侧可再加 (resource_id, teacher_id) WHERE end_time IS NULL
# 部分唯一索引兜底多实例部署。
_teaching_write_lock = threading.Lock()


def _current_teacher():
    if session.get('is_admin'):
        return None, '管理员'
    return session.get('teacher_id'), session.get('teacher_name') or '教师'


def _attendance_snapshot(class_id=None):
    # 教师数据边界：非管理员教师只能看本人任课班级的名单/IP，
    # 否则任一教师（含全校共享只读码会话）可拉取任意活跃班的学生隐私
    allowed_class_ids = None
    if session.get('is_teacher') and not session.get('is_admin'):
        from app.services.resource_access import teacher_class_ids
        allowed_class_ids = teacher_class_ids(session.get('teacher_id'))
        if class_id and class_id not in allowed_class_ids:
            class_id = None
    active_class = db.session.get(Class, class_id) if class_id else None
    if active_class is None:
        if allowed_class_ids is not None:
            active_sessions = ClassroomSession.query.filter_by(
                is_active=True).all()
            active_class = next(
                (s.class_ for s in active_sessions
                 if s.class_id in allowed_class_ids and s.class_), None)
        else:
            setting = ClassroomSetting.query.first()
            active_class = setting.active_class if setting and setting.active_class else None
            if active_class is None:
                active = ClassroomSession.query.filter_by(is_active=True).first()
                active_class = active.class_ if active else None
    now = datetime.now()
    cutoff = now - timedelta(minutes=30)
    students_data = []
    online_count = 0
    if active_class:
        students = Student.query.filter_by(class_id=active_class.id).order_by(
            Student.student_number, Student.name).all()
        for student in students:
            seen_at = student.last_seen or student.login_time
            is_online = bool(seen_at and seen_at >= cutoff)
            if is_online:
                online_count += 1
            students_data.append({
                'id': student.id,
                'name': student.name,
                'student_number': student.student_number,
                'is_online': is_online,
                'last_seen': seen_at.strftime('%Y-%m-%d %H:%M:%S') if seen_at else None,
                'ip_address': student.ip_address or '',
            })
    return {
        'time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'class_name': active_class.name if active_class else '',
        'online_count': online_count,
        'total': len(students_data),
        'students': students_data,
    }


def _teacher_primary_class_id():
    """教师上课记录归属班级：优先表单/唯一任课班/唯一当前会话。"""
    form_id = parse_int(request.form.get('class_id', '').strip())
    if form_id:
        if not db.session.get(Class, form_id):
            return None
        if session.get('is_admin'):
            return form_id
        from app.services.resource_access import teacher_class_ids
        allowed = teacher_class_ids(session.get('teacher_id'))
        return form_id if form_id in allowed else None
    if session.get('is_admin'):
        active = ClassroomSession.query.filter_by(is_active=True).first()
        return active.class_id if active else None
    from app.services.resource_access import teacher_class_ids
    ids = teacher_class_ids(session.get('teacher_id'))
    if len(ids) == 1:
        return next(iter(ids))
    active_ids = {s.class_id for s in ClassroomSession.query.filter_by(
        is_active=True).all()}
    overlap = ids & active_ids
    if len(overlap) == 1:
        return next(iter(overlap))
    return next(iter(ids)) if ids else None


@teaching_bp.route('/teaching-center/start_class/<int:res_id>', methods=['POST'])
@teacher_login_required
def start_class(res_id):
    if not SystemConfig.get_bool('class_buttons_enabled', True):
        flash('上课功能已被管理员关闭', 'danger')
        return redirect(url_for('resources.study', mode='classroom'))
    resource = db.get_or_404(Resource, res_id)
    teacher_id, teacher_name = _current_teacher()
    class_id = _teacher_primary_class_id()
    with _teaching_write_lock:
        # 按 teacher_id 查重（显示名相同的教师互不干扰）；
        # teacher_id 缺失（管理员操作等）时回退 teacher_name
        _existing_query = TeachingSession.query.filter_by(
            resource_id=res_id, end_time=None)
        existing = (
            _existing_query.filter_by(teacher_id=teacher_id).first()
            if teacher_id else _existing_query.filter_by(teacher_name=teacher_name).first()
        )
        if existing:
            flash('您已在该资源上开始了课堂', 'warning')
            return redirect(url_for('resources.study', mode='classroom'))
        snapshot = {'start': _attendance_snapshot(class_id)}
        record = TeachingSession(
            resource_id=resource.id,
            teacher_id=teacher_id,
            teacher_name=teacher_name,
            class_id=class_id,
            attendance_snapshot=json.dumps(snapshot, ensure_ascii=False),
            status='active'
        )
        db.session.add(record)
        db.session.commit()
    flash(f'已开始上课：{resource.title}', 'success')
    return redirect(url_for('resources.study', mode='classroom'))


@teaching_bp.route('/teaching-center/end_class/<int:res_id>', methods=['POST'])
@teacher_login_required
def end_class(res_id):
    if not SystemConfig.get_bool('class_buttons_enabled', True):
        flash('下课功能已被管理员关闭', 'danger')
        return redirect(url_for('resources.study', mode='classroom'))
    teacher_id, teacher_name = _current_teacher()
    requested_class_id = parse_int(request.form.get('class_id', '').strip())
    with _teaching_write_lock:
        _record_query = TeachingSession.query.filter_by(
            resource_id=res_id, end_time=None)
        if requested_class_id:
            _record_query = _record_query.filter_by(class_id=requested_class_id)
        record = (
            _record_query.filter_by(teacher_id=teacher_id).order_by(
                TeachingSession.start_time.desc()).first()
            if teacher_id else _record_query.filter_by(teacher_name=teacher_name).order_by(
                TeachingSession.start_time.desc()).first()
        )
        if not record:
            flash('未找到进行中的课堂记录', 'warning')
            return redirect(url_for('resources.study', mode='classroom'))
        record.end_time = datetime.now()
        record.duration_minutes = max(0, int((record.end_time - record.start_time).total_seconds() // 60))
        record.status = 'ended'
        try:
            snapshot = json.loads(record.attendance_snapshot or '{}')
        except Exception:
            snapshot = {}
        snapshot['end'] = _attendance_snapshot(record.class_id)
        record.attendance_snapshot = json.dumps(snapshot, ensure_ascii=False)
        db.session.flush()
        # 该班没有任何进行中的教学记录时，下课同时停用班级课堂会话。
        # 学生会话绑定的是 ClassroomSession；若只结束 TeachingSession，
        # 学生仍保持登录并看到全局资源，违背“下课后会话立即失效”。
        closed_session = False
        if record.class_id and not TeachingSession.query.filter_by(
                class_id=record.class_id, end_time=None).first():
            ClassroomSession.query.filter_by(
                class_id=record.class_id).update(
                    {ClassroomSession.is_active: False}, synchronize_session=False)
            setting = ClassroomSetting.query.first()
            if setting and setting.active_class_id == record.class_id:
                setting.active_class_id = None
                setting.current_schedule_id = None
            # 清空该班登录/心跳痕迹，配合 active 缓存失效让下一次请求
            # 触发学生会话清理。
            Student.query.filter_by(class_id=record.class_id).update(
                {Student.login_time: None, Student.last_seen: None,
                 Student.ip_address: None}, synchronize_session=False)
            closed_session = True
        db.session.commit()
        # 先提交再失效缓存：避免提交前并发请求按旧 DB 状态重建缓存，
        # 造成下课状态在 TTL 内回退。
        if closed_session:
            invalidate_active_class_cache()
            sse_bump('classroom')
    flash('已下课并保存教学记录', 'success')
    return redirect(url_for('resources.study', mode='classroom'))


@teaching_bp.route('/admin/teaching-sessions')
@teaching_bp.route('/teacher/teaching-sessions')
@teacher_login_required
def teaching_sessions():
    query = TeachingSession.query
    # 普通教师仅可见自己的课堂记录（考勤快照含学生姓名/IP，属教师间横向信息）；
    # 管理员可见全部
    if not session.get('is_admin'):
        teacher_id = session.get('teacher_id')
        query = query.filter(TeachingSession.teacher_id == teacher_id)
    from app.utils import paginate_query
    from sqlalchemy.orm import joinedload as _jl
    pagination = paginate_query(
        query.options(_jl(TeachingSession.resource)).order_by(
            TeachingSession.start_time.desc()),
        default_per_page=20, max_per_page=100
    )
    return render_template('teaching_sessions.html', records=pagination.items,
                           pagination=pagination)


@teaching_bp.route('/teaching-sessions/<int:session_id>/delete', methods=['POST'])
@teacher_login_required
def delete_teaching_session(session_id):
    """删除单条教学记录：管理员可删全部，教师只能删自己的记录。"""
    record = db.get_or_404(TeachingSession, session_id)
    is_admin = bool(session.get('is_admin'))
    teacher_id = session.get('teacher_id')
    if not is_admin and (not teacher_id or record.teacher_id != teacher_id):
        # 教师不能删除他人记录，也不能删除管理员代课产生的无 teacher_id 记录
        abort(403)
    label = '{} / {}'.format(
        record.resource.title if record.resource else '资源已删除',
        record.start_time.strftime('%Y-%m-%d %H:%M') if record.start_time else '未知时间')
    db.session.delete(record)
    db.session.commit()
    flash(f'已删除教学记录：{label}', 'success')
    # 保留来源页与分页；只接受站内路径，防开放跳转
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt:
        return redirect(nxt)
    return redirect(url_for('teaching.teaching_sessions'))
