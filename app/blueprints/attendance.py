"""
签到管理蓝图
功能：实时签到状态显示、按班级查看、自动刷新、未签到高亮、
      每日签到历史记录（按日期/班级筛选与导出）
"""
from datetime import date, datetime

from flask import Blueprint, request, render_template, send_file, jsonify
from app.decorators import admin_login_required
from app.extensions import db
from app.utils import get_classes_cached, parse_int

attendance_bp = Blueprint('attendance', __name__, url_prefix='')


@attendance_bp.route('/admin/attendance')
@admin_login_required
def admin_attendance():
    """签到管理页面"""
    classes = get_classes_cached()
    class_id = request.args.get('class_id', '', type=str)
    return render_template('admin_attendance.html',
                           classes=classes,
                           class_id=class_id,
                           today=date.today().strftime('%Y-%m-%d'))


@attendance_bp.route('/admin/attendance/history')
@admin_login_required
def attendance_history():
    """每日签到历史查询（日期 + 班级筛选，懒补全离线记录）"""
    from app.services.attendance_service import get_history
    from app.models import Class
    date_str = request.args.get('date', '')
    class_id = request.args.get('class_id', '', type=str)
    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        return jsonify({'success': False, 'message': '日期格式无效'}), 400
    cid = parse_int(class_id)
    if not cid:
        return jsonify({'success': False, 'message': '请选择班级'}), 400
    cls = db.session.get(Class, cid)
    if not cls:
        return jsonify({'success': False, 'message': '班级不存在'}), 404
    records, stats = get_history(query_date, cid)
    data = [{
        'student_number': '',
        'name': r.name,
        'status': r.status,
        'login_time': r.login_time.strftime('%Y-%m-%d %H:%M:%S') if r.login_time else '',
        'last_seen': r.last_seen.strftime('%Y-%m-%d %H:%M:%S') if r.last_seen else '',
        'seat_number': r.seat_number,
    } for r in records]
    # 补充学号
    from app.models import Student
    sid_map = {s.id: s for s in Student.query.filter(
        Student.id.in_([r.student_id for r in records])).all()}
    for item, r in zip(data, records):
        stu = sid_map.get(r.student_id)
        item['student_number'] = stu.student_number if stu else ''
    return jsonify({'success': True, 'data': {
        'date': str(query_date),
        'class_name': cls.name,
        'stats': stats,
        'records': data,
    }})


@attendance_bp.route('/admin/attendance/export')
@admin_login_required
def attendance_export():
    """导出指定日期+班级的签到记录为 Excel"""
    from app.services.attendance_service import export_history
    from app.models import Class
    date_str = request.args.get('date', '')
    class_id = request.args.get('class_id', '', type=str)
    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        return '日期格式无效', 400
    cid = parse_int(class_id)
    if not cid:
        return '请选择班级', 400
    cls = db.session.get(Class, cid)
    if not cls:
        return '班级不存在', 404
    buf = export_history(query_date, cid, cls.name)
    return send_file(buf, as_attachment=True,
                     download_name=f'{cls.name}_签到_{query_date.strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
