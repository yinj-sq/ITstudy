from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask import current_app
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from app.extensions import db
from app.models import Student
from app.decorators import admin_login_required
from app.utils import excel_safe
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from flask import send_file

students_bp = Blueprint('students', __name__, url_prefix='')


@students_bp.route('/admin/online_students')
@admin_login_required
def admin_online_students():
    """管理员查看在线学生页面"""
    thirty_mins_ago = datetime.now() - timedelta(minutes=30)
    sort = request.args.get('sort', 'login_time')
    order = request.args.get('order', 'desc')
    online_filter = or_(
        Student.last_seen >= thirty_mins_ago,
        (Student.last_seen.is_(None) & (Student.login_time >= thirty_mins_ago))
    )
    query = Student.query.filter(online_filter)
    if sort == 'name':
        query = query.order_by(Student.name.asc() if order == 'asc' else Student.name.desc())
    elif sort == 'student_class':
        query = query.order_by(Student.student_class.asc() if order == 'asc' else Student.student_class.desc())
    elif sort == 'ip_address':
        query = query.order_by(Student.ip_address.asc() if order == 'asc' else Student.ip_address.desc())
    else:
        seen_expr = func.coalesce(Student.last_seen, Student.login_time)
        query = query.order_by(seen_expr.asc() if order == 'asc' else seen_expr.desc())
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 10
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    online_students = pagination.items
    return render_template('admin_online_students.html',
                           students=online_students,
                           current_time=datetime.now(),
                           pagination=pagination,
                           sort=sort,
                           order=order,
                           total=pagination.total)


@students_bp.route('/admin/online_students/export')
@admin_login_required
def export_online_students():
    """导出在线学生列表为Excel文件"""
    try:
        thirty_mins_ago = datetime.now() - timedelta(minutes=30)
        online_filter = or_(
            Student.last_seen >= thirty_mins_ago,
            (Student.last_seen.is_(None) & (Student.login_time >= thirty_mins_ago))
        )
        online_students = Student.query.filter(online_filter).order_by(
            func.coalesce(Student.last_seen, Student.login_time).desc()).all()
        wb = Workbook()
        ws = wb.active
        ws.title = "在线学生"
        headers = ['姓名', '班级', 'IP地址', '登录时间']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
        for i, student in enumerate(online_students, 2):
            # 姓名/班级/IP 等用户可控文本套 excel_safe 防公式注入
            ws.cell(row=i, column=1, value=excel_safe(student.name))
            ws.cell(row=i, column=2, value=excel_safe(student.student_class))
            ws.cell(row=i, column=3, value=excel_safe(student.ip_address))
            seen = student.last_seen or student.login_time
            ws.cell(row=i, column=4, value=excel_safe(seen.strftime('%Y-%m-%d %H:%M:%S') if seen else ''))
        for col in range(1, 5):
            ws.column_dimensions[chr(64 + col)].width = 20
        file_stream = BytesIO()
        wb.save(file_stream)
        file_stream.seek(0)
        current_app.logger.info("管理员导出了在线学生列表")
        return send_file(
            file_stream,
            as_attachment=True,
            download_name=f"在线学生_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        current_app.logger.error(f"导出在线学生列表失败: {str(e)}", exc_info=True)
        flash('导出失败', 'danger')
        return redirect(url_for('students.admin_online_students'))


@students_bp.route('/admin/online_students/clear', methods=['POST'])
@admin_login_required
def clear_online_students():
    """清除在线学生列表"""
    try:
        thirty_mins_ago = datetime.now() - timedelta(minutes=30)
        online_filter = or_(
            Student.last_seen >= thirty_mins_ago,
            (Student.last_seen.is_(None) & (Student.login_time >= thirty_mins_ago))
        )
        one_year_ago = datetime.now() - timedelta(days=365)
        # 单条 UPDATE 替代全列加载后逐行赋值（与 API 版一致）
        count_before = Student.query.filter(online_filter).update(
            {'login_time': one_year_ago, 'last_seen': one_year_ago},
            synchronize_session=False)
        db.session.commit()
        current_app.logger.info(f"管理员清除了在线学生列表，共 {count_before} 名学生")
        flash(f'已清除 {count_before} 名在线学生', 'success')
    except Exception as e:
        db.session.rollback()
        flash('清除失败', 'danger')
        current_app.logger.error(f"清除在线学生列表失败: {str(e)}")
    return redirect(url_for('students.admin_online_students'))
