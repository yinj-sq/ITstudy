"""由 API 门面模块加载的领域路由。"""
from datetime import datetime, timedelta

from flask import jsonify, request

from app.models import (
    Class, ClassroomSetting, ClassroomSession, Student,
)
from app.decorators import admin_login_required
from app.utils import (
    parse_int,
)
from app.blueprints.api import (
    api_bp, _calc_seat,
)

# ──────────────────────────────────────────────
#  Attendance API
# ──────────────────────────────────────────────


@api_bp.route('/attendance/status', methods=['GET'])
@admin_login_required
def api_attendance_status():
    """获取签到状态（含座位号）

    性能：考勤页 10s 轮询热路径，未传 class_id 时此前全表扫描
    （250 人全列 + 逐行组查询）。5s TTL 缓存（考勤数据容忍秒级延迟）。
    """
    from app.extensions import cache as _att_cache
    class_id = request.args.get('class_id', '', type=str)
    cache_key = f'attendance:status:{class_id or "all"}'
    cached = _att_cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    thirty_mins_ago = datetime.now() - timedelta(minutes=30)
    setting = ClassroomSetting.query.first()
    seat_offset = setting.seat_offset if setting else 0
    if class_id:
        cid_for_session = parse_int(class_id)
        att_session = ClassroomSession.query.filter_by(
            class_id=cid_for_session, is_active=True).first() if cid_for_session else None
        if att_session:
            seat_offset = att_session.seat_offset or 0

    if class_id:
        cid = parse_int(class_id)
        students = Student.query.with_entities(
            Student.id, Student.name, Student.student_number,
            Student.student_class, Student.class_id, Student.group_id,
            Student.ip_address, Student.last_seen, Student.login_time
        ).filter_by(class_id=cid).order_by(
            Student.student_number, Student.name).all() if cid is not None else []
    else:
        students = Student.query.with_entities(
            Student.id, Student.name, Student.student_number,
            Student.student_class, Student.class_id, Student.group_id,
            Student.ip_address, Student.last_seen, Student.login_time
        ).order_by(
            Student.class_id, Student.student_number, Student.name).all()

    classes_map = {c.id: c.name for c in Class.query.all()}
    # 批量加载小组名，避免循环内 s.group lazy load 造成 N+1
    group_ids = {s.group_id for s in students if s.group_id is not None}
    groups_map = {}
    if group_ids:
        from app.models import StudyGroup
        groups_map = {g.id: g.name for g in StudyGroup.query.filter(StudyGroup.id.in_(group_ids)).all()}
    result = []
    checked_in = 0
    for s in students:
        seen_at = s.last_seen or s.login_time
        is_online = bool(seen_at and seen_at >= thirty_mins_ago)
        if is_online:
            checked_in += 1
        seat = _calc_seat(s.ip_address, seat_offset)
        result.append({
            'id': s.id, 'name': s.name, 'student_number': s.student_number,
            'student_class': s.student_class,
            'class_name': classes_map.get(s.class_id, s.student_class or '未分班'),
            'class_id': s.class_id,
            'group_name': groups_map.get(s.group_id, ''),
            'is_online': is_online,
            'login_time': seen_at.strftime('%Y-%m-%d %H:%M:%S') if seen_at else None,
            'ip_address': s.ip_address or '',
            'seat_number': seat
        })

    total = len(result)
    resp_data = {
        'success': True,
        'data': {
            'students': result,
            'checked_in': checked_in,
            'total': total,
            'check_in_rate': round(checked_in / total * 100, 1) if total > 0 else 0,
            'refresh_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'seat_offset': seat_offset
        }
    }
    _att_cache.set(cache_key, resp_data, timeout=5)
    return jsonify(resp_data)
