"""
课堂管理蓝图
功能：作息时间表管理、上课班级设置、大屏展示
"""
from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify, send_file, session, abort
from flask import current_app
from datetime import datetime, timedelta
import re
import threading
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import (Class, Student, Schedule, ClassroomSetting,
                        ClassroomSession, ClassSchedule, Appeal)
from app.decorators import (admin_login_required, teacher_login_required,
                            teacher_edit_required)
from app.blueprints.auth import invalidate_active_class_cache
from app.services.resource_access import teacher_class_ids, teacher_classes
from app.utils import get_classes_cached, get_schedules_cached, invalidate_lookup_cache, parse_int
from app.blueprints.api import _calc_seat

classroom_bp = Blueprint('classroom', __name__, url_prefix='')

# 自动切换上课班级的进程内互斥锁：切换发生在 GET 端点（大屏轮询/多标签页），
# 并发请求可能互相覆盖 current_schedule_id / 重复清空学生登录信息
_active_class_switch_lock = threading.Lock()

# 时段时间字段格式校验：HH:MM。格式不正确时大屏/自动切换的字符串比较会错位
_TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')

# 课程表自动切班提前量：在节次开始前 5 分钟切换，便于学生提前进入课堂。
AUTO_SWITCH_LEAD_MINUTES = 5


def _time_to_minutes(value):
    """HH:MM → 当日分钟数；非法时间返回 None。"""
    if not _valid_time_str(value):
        return None
    hh, mm = map(int, str(value).strip().split(':'))
    return hh * 60 + mm


def _auto_period_for_now(schedules, now=None, lead_minutes=AUTO_SWITCH_LEAD_MINUTES):
    """返回当前应自动切换到的节次（含开始前 lead_minutes 的提前量）。

    与页面显示用的“当前节次”不同：自动切班需要在正式上课前把班级、
    在线名单和签到状态提前切过去，因此窗口是
    [start - lead_minutes, end]。多个节次重叠时按开始时间取最早命中项。
    """
    now = now or datetime.now()
    now_min = now.hour * 60 + now.minute
    ordered = sorted(schedules, key=lambda s: (s.start_time, s.end_time))
    for s in ordered:
        start = _time_to_minutes(s.start_time)
        end = _time_to_minutes(s.end_time)
        if start is None or end is None:
            continue
        if start - lead_minutes <= now_min <= end:
            return s
    return None


def _valid_time_str(value):
    """校验时间字符串是否为合法 HH:MM（如 08:30 / 9:05），非法返回 False"""
    s = str(value or '').strip()
    if not _TIME_RE.match(s):
        return False
    try:
        hh, mm = map(int, s.split(':'))
    except ValueError:
        return False
    return 0 <= hh < 24 and 0 <= mm < 60


def _normalize_time(value):
    """时间字符串零填充归一化：'9:05' → '09:05'。

    大屏/自动切班用 s.start_time <= current_time（strftime '%H:%M' 零填充）
    字符串比较，'9:05' > '09:05' 永不命中会导致该时段自动切班静默失效。
    所有入库路径存储前调用本函数归一化。
    """
    s = str(value or '').strip()
    if not _valid_time_str(s):
        return s
    hh, mm = map(int, s.split(':'))
    return f'{hh:02d}:{mm:02d}'


def _valid_time_range(start_value, end_value):
    """校验时段起止合法性：格式合法且 end > start。

    倒置时段（end <= start）会使大屏/自动切课的字符串比较永不命中，
    学生端永远显示"课间休息"。
    """
    if not _valid_time_str(start_value) or not _valid_time_str(end_value):
        return False
    return str(start_value).strip() < str(end_value).strip()

# 星期映射表（复用模型中的常量定义，避免重复）
_WEEKDAY_NAMES = ClassSchedule.WEEKDAY_NAMES


def _parse_weekday(value):
    """解析星期格式为整数 1-7（1=星期一，7=星期日），无法识别返回 None"""
    if value is None:
        return None
    s = str(value).strip()
    try:
        n = int(s)
        if 1 <= n <= 7:
            return n
    except ValueError:
        pass
    cn_map = {'星期一': 1, '星期二': 2, '星期三': 3, '星期四': 4, '星期五': 5, '星期六': 6, '星期日': 7, '星期天': 7}
    if s in cn_map:
        return cn_map[s]
    cn_short = {'周一': 1, '周二': 2, '周三': 3, '周四': 4, '周五': 5, '周六': 6, '周日': 7}
    if s in cn_short:
        return cn_short[s]
    en_map = {'monday': 1, 'mon': 1, 'tuesday': 2, 'tue': 2, 'wednesday': 3, 'wed': 3,
              'thursday': 4, 'thu': 4, 'friday': 5, 'fri': 5, 'saturday': 6, 'sat': 6,
              'sunday': 7, 'sun': 7}
    if s.lower() in en_map:
        return en_map[s.lower()]
    return None


def _seen_at(student):
    return student.last_seen or student.login_time


def _period_number_for_schedule(schedule_id, ordered_schedules=None):
    """作息时段在有序作息表中的 1 基节次序号（供课程表 period_number 匹配）。

    ClassSchedule.period_number 语义为"第 N 节课"（1 基，由导入 Excel 填写），
    而 Schedule.sort_order 在不同创建路径下可能是 0 基或 1 基、且可能有间隙，
    直接用 sort_order 去匹配 period_number 会错位。统一改用时段在有序作息表中的位置。
    """
    if ordered_schedules is None:
        ordered_schedules = get_schedules_cached()
    for idx, s in enumerate(ordered_schedules, 1):
        if s.id == schedule_id:
            return idx
    return None


# ──────────────────────────────────────────────
#  作息时间表管理
# ──────────────────────────────────────────────


@classroom_bp.route('/admin/schedule')
@admin_login_required
def admin_schedule():
    """作息时间表管理页面"""
    schedules = Schedule.query.order_by(Schedule.sort_order, Schedule.start_time).all()
    return render_template('admin_schedule.html', schedules=schedules)


@classroom_bp.route('/teacher/schedule')
@teacher_login_required
def teacher_schedule():
    """教师端只读作息时间表/本人班级课程表。

    教师登录后不再只依赖课堂页的「今日作息」侧栏：即使当前没有激活的
    上课班级，也能从导航直接查看管理员维护的作息和任课班级课程表。
    """
    if session.get('is_admin'):
        return redirect(url_for('classroom.admin_schedule'))
    schedules = get_schedules_cached()
    classes = teacher_classes(session.get('teacher_id'))
    class_names = {c.name for c in classes}
    entries = []
    if class_names:
        entries = ClassSchedule.query.filter(
            ClassSchedule.class_name.in_(class_names)).order_by(
            ClassSchedule.weekday, ClassSchedule.period_number).all()
    entry_map = {}
    for entry in entries:
        entry_map.setdefault((entry.weekday, entry.period_number), []).append(entry)
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    current_period = next(
        (s for s in schedules if s.start_time <= current_time <= s.end_time),
        None)
    return render_template(
        'teacher_schedule.html', schedules=schedules, classes=classes,
        entry_map=entry_map, weekday_names=_WEEKDAY_NAMES,
        today_weekday=now.weekday() + 1, current_period=current_period)


@classroom_bp.route('/teacher/schedule/add', methods=['POST'])
@teacher_edit_required
def teacher_add_schedule_entry():
    """教师编辑模式为自己的任课班级追加课程表映射。"""
    teacher_id = session.get('teacher_id')
    own_class_names = {c.name for c in teacher_classes(teacher_id)}
    weekday = _parse_weekday(request.form.get('weekday', ''))
    period_number = parse_int(request.form.get('period_number', '').strip())
    class_name = request.form.get('class_name', '').strip()
    schedules = get_schedules_cached()
    if weekday is None or not period_number or period_number < 1 or not class_name:
        flash('请选择星期、节次和班级', 'danger')
    elif not own_class_names or class_name not in own_class_names:
        flash('只能添加本人任课班级的课程', 'danger')
    elif period_number > len(schedules):
        flash('节次超出当前作息时间表范围，请联系管理员设置作息', 'danger')
    elif ClassSchedule.query.filter_by(
            weekday=weekday, period_number=period_number,
            class_name=class_name).first():
        flash('该节次已包含这个班级', 'warning')
    else:
        db.session.add(ClassSchedule(
            weekday=weekday, period_number=period_number,
            class_name=class_name))
        db.session.commit()
        invalidate_active_class_cache()
        flash('课程安排已添加', 'success')
    return redirect(url_for('classroom.teacher_schedule'))


@classroom_bp.route('/teacher/schedule/<int:entry_id>/delete', methods=['POST'])
@teacher_edit_required
def teacher_delete_schedule_entry(entry_id):
    """教师编辑模式删除本人任课班级的课程表条目。"""
    entry = db.session.get(ClassSchedule, entry_id)
    if not entry:
        abort(404)
    own_class_names = {c.name for c in teacher_classes(session.get('teacher_id'))}
    if entry.class_name not in own_class_names:
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    invalidate_active_class_cache()
    flash('课程安排已删除', 'success')
    return redirect(url_for('classroom.teacher_schedule'))


@classroom_bp.route('/admin/schedule/add', methods=['POST'])
@admin_login_required
def add_schedule():
    """添加作息时段"""
    period_name = request.form.get('period_name', '').strip()
    start_time = request.form.get('start_time', '').strip()
    end_time = request.form.get('end_time', '').strip()
    if not period_name or not start_time or not end_time:
        flash('请填写完整信息', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    if not _valid_time_range(start_time, end_time):
        flash('时间无效：请使用 HH:MM 格式且结束时间晚于开始时间', 'danger')
        return redirect(url_for('classroom.admin_schedule'))

    max_order = db.session.query(db.func.max(Schedule.sort_order)).scalar() or 0
    s = Schedule(
        period_name=period_name,
        start_time=_normalize_time(start_time),
        end_time=_normalize_time(end_time),
        sort_order=max_order + 1
    )
    db.session.add(s)
    db.session.commit()
    invalidate_lookup_cache('schedules')
    flash(f'时段 "{period_name}" ({start_time}-{end_time}) 已添加', 'success')
    return redirect(url_for('classroom.admin_schedule'))


@classroom_bp.route('/admin/schedule/<int:sid>/edit', methods=['POST'])
@admin_login_required
def edit_schedule(sid):
    """编辑作息时段"""
    s = db.get_or_404(Schedule, sid)
    new_start = request.form.get('start_time', '').strip()
    new_end = request.form.get('end_time', '').strip()
    if not _valid_time_range(new_start, new_end):
        flash('时间无效：请使用 HH:MM 格式且结束时间晚于开始时间', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    s.period_name = request.form.get('period_name', '').strip()
    s.start_time = _normalize_time(new_start)
    s.end_time = _normalize_time(new_end)
    s.is_active = request.form.get('is_active', '') == 'true'
    db.session.commit()
    invalidate_lookup_cache('schedules')
    flash(f'时段 "{s.period_name}" 已更新', 'success')
    return redirect(url_for('classroom.admin_schedule'))


@classroom_bp.route('/admin/schedule/<int:sid>/delete', methods=['POST'])
@admin_login_required
def delete_schedule(sid):
    """删除作息时段"""
    s = db.get_or_404(Schedule, sid)
    # 解除课堂设置对该时段的引用（FK 无级联，直接删会 500）
    ClassroomSetting.query.filter_by(current_schedule_id=sid).update(
        {ClassroomSetting.current_schedule_id: None}, synchronize_session=False)
    ClassroomSession.query.filter_by(schedule_id=sid).update(
        {ClassroomSession.schedule_id: None}, synchronize_session=False)
    db.session.delete(s)
    db.session.commit()
    invalidate_lookup_cache('schedules')
    flash(f'时段 "{s.period_name}" 已删除', 'success')
    return redirect(url_for('classroom.admin_schedule'))


@classroom_bp.route('/admin/schedule/sort', methods=['POST'])
@admin_login_required
def sort_schedule():
    """更新排序"""
    ids_str = request.form.get('ids', '')
    if ids_str:
        # 静默过滤非数字元素（此前直接 int() 会抛 ValueError → 500）
        ids = []
        for part in ids_str.split(','):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        for idx, sid in enumerate(ids):
            s = db.session.get(Schedule, sid)
            if s:
                s.sort_order = idx
        db.session.commit()
        invalidate_lookup_cache('schedules')
    return jsonify({'success': True})


@classroom_bp.route('/admin/schedule/export')
@admin_login_required
def export_schedule():
    """导出作息时间表为 Excel（节次/开始/结束/启用）"""
    from io import BytesIO
    try:
        import openpyxl
    except ImportError:
        flash('请安装 openpyxl: pip install openpyxl', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '作息时间表'
    ws.append(['节次名称', '开始时间', '结束时间', '是否启用'])
    for s in Schedule.query.order_by(Schedule.sort_order, Schedule.start_time).all():
        ws.append([s.period_name, s.start_time, s.end_time, '是' if s.is_active else '否'])
    # 列宽
    for col, w in zip('ABCD', [24, 12, 12, 12]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f'作息时间表_{datetime.now().strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@classroom_bp.route('/admin/schedule/import', methods=['POST'])
@admin_login_required
def import_schedule():
    """从 Excel 导入作息时间表（全量替换；格式与导出模板一致）"""
    from io import BytesIO
    if 'file' not in request.files:
        flash('请选择要导入的 Excel 文件', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    f = request.files['file']
    if not f or not f.filename:
        flash('请选择要导入的 Excel 文件', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(f.read()), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception:
        flash('Excel 解析失败，请使用导出的模板格式', 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    if not rows:
        flash('Excel 文件为空', 'danger')
        return redirect(url_for('classroom.admin_schedule'))

    new_schedules = []
    errors = []
    for row_num, row in enumerate(rows, 1):
        # 跳过表头行
        if row_num == 1:
            first = str(row[0]).strip() if row and row[0] else ''
            if first in ('节次名称', '时段名称', 'period_name'):
                continue
        if not row or not any(str(c).strip() if c is not None else '' for c in row[:3]):
            continue
        period_name = str(row[0]).strip() if row[0] is not None else ''
        start_time = str(row[1]).strip() if len(row) >= 2 and row[1] is not None else ''
        end_time = str(row[2]).strip() if len(row) >= 3 and row[2] is not None else ''
        is_active_raw = str(row[3]).strip() if len(row) >= 4 and row[3] is not None else ''
        if not period_name:
            errors.append(f'第{row_num}行: 节次名称为空')
            continue
        if not _valid_time_range(start_time, end_time):
            errors.append(f'第{row_num}行: 时间无效（需 HH:MM 且结束晚于开始）')
            continue
        is_active = is_active_raw in ('是', '1', 'true', 'TRUE', '启用', 'yes', 'YES')
        new_schedules.append((period_name, _normalize_time(start_time),
                              _normalize_time(end_time), is_active))

    if errors:
        for err in errors[:5]:
            flash(err, 'danger')
        return redirect(url_for('classroom.admin_schedule'))
    if not new_schedules:
        flash('未解析到有效的作息时段', 'danger')
        return redirect(url_for('classroom.admin_schedule'))

    # 全量替换（与页面保存语义一致）
    # 先解除 classroom_setting 对旧时段的引用（FK 无级联，直接 DELETE 全部时段会失败）
    ClassroomSetting.query.update({ClassroomSetting.current_schedule_id: None}, synchronize_session=False)
    ClassroomSession.query.update({ClassroomSession.schedule_id: None}, synchronize_session=False)
    Schedule.query.delete()
    for sort_order, (period_name, start_time, end_time, is_active) in enumerate(new_schedules):
        db.session.add(Schedule(period_name=period_name, start_time=start_time,
                                end_time=end_time, is_active=is_active, sort_order=sort_order))
    db.session.commit()
    invalidate_lookup_cache('schedules')
    flash(f'已导入 {len(new_schedules)} 个作息时段', 'success')
    return redirect(url_for('classroom.admin_schedule'))


# ──────────────────────────────────────────────
#  课程表管理
# ──────────────────────────────────────────────


@classroom_bp.route('/admin/class_schedule')
@admin_login_required
def admin_class_schedule():
    """课程表管理页面"""
    schedules = get_schedules_cached()
    entries = ClassSchedule.query.order_by(ClassSchedule.weekday, ClassSchedule.period_number).all()
    classes = get_classes_cached()
    # 构建 {(weekday, period_number): [entry]} 映射（同节次可多班）
    entry_map = {}
    for e in entries:
        entry_map.setdefault((e.weekday, e.period_number), []).append(e)
    today_weekday = datetime.now().weekday() + 1
    return render_template('admin_class_schedule.html',
                           schedules=schedules, entry_map=entry_map, classes=classes,
                           weekday_names=_WEEKDAY_NAMES, today_weekday=today_weekday)


@classroom_bp.route('/admin/class_schedule/add', methods=['POST'])
@admin_login_required
def add_class_schedule_entry():
    """追加一条课程表映射（同一节次可添加多个班级）。"""
    weekday = _parse_weekday(request.form.get('weekday', ''))
    period_number = parse_int(request.form.get('period_number', '').strip())
    class_name = request.form.get('class_name', '').strip()
    if weekday is None or not period_number or period_number < 1 or not class_name:
        flash('请选择星期、节次和班级', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))
    if not Class.query.filter_by(name=class_name).first():
        flash('所选班级不存在', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))
    exists = ClassSchedule.query.filter_by(
        weekday=weekday, period_number=period_number,
        class_name=class_name).first()
    if exists:
        flash('该节次已包含这个班级', 'warning')
    else:
        db.session.add(ClassSchedule(
            weekday=weekday, period_number=period_number,
            class_name=class_name))
        db.session.commit()
        flash('课程表映射已添加', 'success')
    return redirect(url_for('classroom.admin_class_schedule'))


@classroom_bp.route('/admin/class_schedule/export')
@admin_login_required
def export_class_schedule():
    """导出课程表为 Excel（矩阵：横轴星期、纵轴节次、单元格为班级）"""
    from io import BytesIO
    try:
        import openpyxl
    except ImportError:
        flash('请安装 openpyxl: pip install openpyxl', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))
    schedules = get_schedules_cached()
    entries = ClassSchedule.query.order_by(
        ClassSchedule.weekday, ClassSchedule.period_number).all()
    entry_map = {}
    for e in entries:
        entry_map.setdefault((e.weekday, e.period_number), []).append(e.class_name)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '课程表'
    # 表头：星期
    weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
    ws.cell(row=1, column=1, value='节次')
    for col, name in enumerate(weekdays, 2):
        ws.cell(row=1, column=col, value=name)
    # 行：按作息时间表节次顺序（无作息表时按第N节）
    if schedules:
        for idx, s in enumerate(schedules, 2):
            ws.cell(row=idx, column=1, value=f'{s.period_name}({s.start_time}-{s.end_time})')
            # 节次位置用 enumerate 序号（1 基位置），与 _period_number_for_schedule
            # 语义一致——sort_order 可能有间隙（删除时段后），+1 假设会错位
            for wd in range(1, 8):
                ws.cell(row=idx, column=wd + 1,
                        value='、'.join(entry_map.get((wd, idx - 1), [])) or '')
    else:
        max_period = max((e.period_number for e in entries), default=0)
        for p in range(1, max_period + 1):
            ws.cell(row=p + 1, column=1, value=f'第{p}节')
            for wd in range(1, 8):
                ws.cell(row=p + 1, column=wd + 1, value='、'.join(entry_map.get((wd, p), [])) or '')
    # 样式：表头加粗
    from openpyxl.styles import Font as _Font
    for cell in ws[1]:
        cell.font = _Font(bold=True)
    for col, w in zip('ABCDEFGH', [18, 14, 14, 14, 14, 14, 14, 14]):
        ws.column_dimensions[col].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f'课程表_{datetime.now().strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@classroom_bp.route('/admin/class_schedule/template')
@admin_login_required
def download_class_schedule_template():
    """下载课程表导入模板"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = '课程表导入模板'
    headers = ['星期', '第N节课', '上课班级']
    header_fill = PatternFill(start_color='C00000', end_color='C00000', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=12)
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    ws.cell(row=2, column=1, value='星期一')
    ws.cell(row=2, column=2, value='1')
    ws.cell(row=2, column=3, value='示例：2024级计算机1班')
    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 30
    # 添加醒目的注意事项
    note_cell = ws.cell(row=4, column=1, value='⚠ 注意：1) 星期可写“星期一/周一/Monday/1”等；2) 第N节课与作息时间表一致；3) 班级名称必须与【班级管理】中的完全一致！')
    note_cell.font = Font(bold=True, color='C00000', size=11)
    ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=3)
    from io import BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True,
                     download_name='课程表导入模板.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@classroom_bp.route('/admin/class_schedule/import', methods=['POST'])
@admin_login_required
def import_class_schedule():
    """导入课程表 Excel"""
    file = request.files.get('excel_file')
    if not file or not file.filename:
        flash('请选择Excel文件', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))
    # openpyxl 只能读 .xlsx（旧版 .xls 为 OLE2 格式，读取即抛错 → 500）
    if not file.filename.lower().endswith('.xlsx'):
        flash('请上传 .xlsx 格式的Excel文件（旧版 .xls 请先另存为 .xlsx）', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))

    import openpyxl
    try:
        wb = openpyxl.load_workbook(file, read_only=True)
    except Exception:
        flash('无法读取该Excel文件，请确认文件未损坏且为 .xlsx 格式', 'danger')
        return redirect(url_for('classroom.admin_class_schedule'))
    ws = wb.active

    all_classes = {c.name for c in Class.query.all()}
    success = 0
    errors = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not row or not row[0]:
            continue
        # 解析三列：星期 | 第N节课 | 上课班级
        try:
            weekday_raw = row[0]
            period_number = int(row[1]) if len(row) > 1 and row[1] else None
            class_name = str(row[2]).strip() if len(row) > 2 and row[2] else ''
        except (ValueError, TypeError):
            errors.append(f'第{row_idx}行：格式不正确')
            continue

        weekday = _parse_weekday(weekday_raw)
        if weekday is None:
            errors.append(f'第{row_idx}行：星期 "{weekday_raw}" 无法识别，请使用“星期一/周一/1”等格式')
            continue
        if period_number is None or period_number < 1:
            errors.append(f'第{row_idx}行：节次格式不正确')
            continue
        if not class_name:
            errors.append(f'第{row_idx}行：班级名称为空')
            continue
        if class_name not in all_classes:
            errors.append(f'第{row_idx}行：班级 "{class_name}" 在班级管理中不存在')
            continue

        existing = ClassSchedule.query.filter_by(
            weekday=weekday, period_number=period_number,
            class_name=class_name).first()
        if not existing:
            db.session.add(ClassSchedule(
                weekday=weekday, period_number=period_number,
                class_name=class_name))
            success += 1
        else:
            # 已存在同一节次的该班级：幂等跳过，不覆盖同节次其他班级
            success += 1

    if success > 0:
        db.session.commit()

    if errors:
        flash(f'导入完成：成功 {success} 行，{len(errors)} 条错误：' + '；'.join(errors[:5]), 'warning')
    else:
        flash(f'成功导入 {success} 条课程表记录', 'success')
    return redirect(url_for('classroom.admin_class_schedule'))


@classroom_bp.route('/admin/class_schedule/clear', methods=['POST'])
@admin_login_required
def clear_class_schedule():
    """清空课程表"""
    ClassSchedule.query.delete()
    db.session.commit()
    flash('课程表已清空', 'success')
    return redirect(url_for('classroom.admin_class_schedule'))


# ──────────────────────────────────────────────
#  课堂设置
# ──────────────────────────────────────────────


def _get_classroom_setting():
    """获取或创建旧单班设置（保留作为 auto_switch 全局开关与兼容兜底）。"""
    setting = ClassroomSetting.query.first()
    if not setting:
        setting = ClassroomSetting()
        db.session.add(setting)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            setting = ClassroomSetting.query.first()
            if not setting:
                raise RuntimeError('无法初始化课堂设置')
    return setting


def _clear_class_login(class_id):
    if class_id:
        Student.query.filter_by(class_id=class_id).update(
            {Student.ip_address: None, Student.login_time: None,
             Student.last_seen: None}, synchronize_session=False)


def _classroom_scope_ids():
    """课堂大屏可见班级范围：管理员 None（全部），教师仅本人任课班级。

    只应在 teacher_login_required 保护的路由内调用；未登录时返回空集合，
    避免意外放大可见范围。
    """
    from flask import session
    if session.get('is_admin'):
        return None
    if session.get('is_teacher'):
        return teacher_class_ids(session.get('teacher_id'))
    return set()


def _classroom_scope_classes():
    """课堂设置下拉里的班级：管理员全部，教师仅本人任课班级。"""
    from flask import session
    if session.get('is_admin'):
        return get_classes_cached()
    return teacher_classes(session.get('teacher_id'))


def _sync_auto_sessions(setting, now=None):
    """课程表自动切班：把当前节次的**所有班级**激活为独立会话。"""
    if not setting or not setting.auto_switch:
        return
    now = now or datetime.now()
    schedules = get_schedules_cached()
    auto_schedule = _auto_period_for_now(schedules, now)
    target_class_ids = set()
    if auto_schedule:
        weekday = now.weekday() + 1
        period_no = _period_number_for_schedule(auto_schedule.id, schedules)
        rows = ClassSchedule.query.filter_by(
            weekday=weekday, period_number=period_no).all() if period_no else []
        for row in rows:
            cls = Class.query.filter_by(name=row.class_name).first()
            if cls:
                target_class_ids.add(cls.id)
    sessions = {s.class_id: s for s in ClassroomSession.query.all()}
    # 无当前节次（课间/放学后/周末/课表未维护）时不做任何停用：
    # 此前 target 为空会把全部会话置停用并 _clear_class_login，学生课间
    # 刷新大屏即被踢出课堂、座位/在线状态清空，直到下一节重新激活。
    # 保留上一节课堂直到下一节开始，与「手工设置班级不被非作息时段清空」一致。
    if not target_class_ids:
        return
    changed = False
    for cid in target_class_ids:
        session = sessions.get(cid)
        if not session:
            session = ClassroomSession(class_id=cid, is_active=True,
                                       auto_switch=True)
            db.session.add(session)
            sessions[cid] = session
            changed = True
        if not session.is_active:
            session.is_active = True
            changed = True
        if session.schedule_id != (auto_schedule.id if auto_schedule else None):
            session.schedule_id = auto_schedule.id if auto_schedule else None
            changed = True
        if not session.auto_switch:
            session.auto_switch = True
            changed = True
    for cid, session in sessions.items():
        if cid not in target_class_ids and session.is_active:
            session.is_active = False
            _clear_class_login(cid)
            changed = True
    if not target_class_ids:
        first_id = None
    elif setting.active_class_id in target_class_ids:
        # 保留已有默认大屏班级，避免多班激活时选择结果随集合迭代顺序变化
        first_id = setting.active_class_id
    else:
        first_id = min(target_class_ids)
    if setting.active_class_id != first_id:
        setting.active_class_id = first_id
        changed = True
    if setting.current_schedule_id != (auto_schedule.id if auto_schedule else None):
        setting.current_schedule_id = auto_schedule.id if auto_schedule else None
        changed = True
    if changed:
        db.session.commit()
        invalidate_active_class_cache()
        from app.utils import sse_bump as _sse_bump
        _sse_bump('classroom')


def _ensure_legacy_session(setting):
    """升级兼容：旧单班设置对应的班级还没有会话时，补一条 ClassroomSession。

    不能只看“是否已有任意会话”：多班部署/历史数据里可能有其他班级的会话，
    甚至已停用或 class_id 为空的行；此前只要有一行就跳过迁移，导致管理员的
    旧单班 active_class 永远没有会话，大屏“新的一课/停用”清不到该班。
    """
    if not setting or not setting.active_class_id:
        return
    if not db.session.get(Class, setting.active_class_id):
        return
    if ClassroomSession.query.filter_by(
            class_id=setting.active_class_id).first() is not None:
        return
    db.session.add(ClassroomSession(
        class_id=setting.active_class_id,
        schedule_id=setting.current_schedule_id,
        display_message=setting.display_message or '',
        seat_offset=setting.seat_offset or 0,
        auto_switch=bool(setting.auto_switch), is_active=True))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _select_session(setting, class_id=None, allowed_class_ids=None):
    # 教师请求不做旧单班迁移：迁移会把管理员设置的上课班建成全局会话，
    # 教师只应看到自己任课班级的会话
    if allowed_class_ids is None:
        _ensure_legacy_session(setting)
    query = ClassroomSession.query.filter_by(is_active=True).order_by(
        ClassroomSession.id)
    session = None
    if class_id:
        if allowed_class_ids is not None and class_id not in allowed_class_ids:
            return None
        session = query.filter_by(class_id=class_id).first()
    if session is None:
        if allowed_class_ids is not None:
            if not allowed_class_ids:
                return None
            query = query.filter(ClassroomSession.class_id.in_(allowed_class_ids))
        session = query.first()
    return session


def _sessions_for_display(class_ids=None):
    query = ClassroomSession.query.filter_by(is_active=True)
    if class_ids is not None:
        if not class_ids:
            return []
        query = query.filter(ClassroomSession.class_id.in_(class_ids))
    return query.order_by(ClassroomSession.id).all()


@classroom_bp.route('/admin/classroom/settings', methods=['POST'])
@teacher_login_required
def save_classroom_settings():
    """保存某个班级的课堂设置（多班各自独立）。

    管理员可设置任意班级并同步全局兼容字段；教师仅能设置本人任课班级，
    且不修改全局 active_class/auto_switch（避免影响其他班级）。
    """
    setting = _get_classroom_setting()
    allowed_class_ids = _classroom_scope_ids()
    is_admin = allowed_class_ids is None
    if is_admin:
        # 升级兼容：首次保存前先保留旧单班设置对应的会话
        _ensure_legacy_session(setting)
    class_id = request.form.get('active_class_id', '').strip()
    schedule_id = request.form.get('current_schedule_id', '').strip()
    display_message = request.form.get('display_message', '').strip()
    seat_offset = request.form.get('seat_offset', '0').strip()

    new_class_id = parse_int(class_id)
    if new_class_id is None or not db.session.get(Class, new_class_id):
        flash('请选择存在的上课班级，请刷新页面后重试', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    if not is_admin and new_class_id not in allowed_class_ids:
        flash('只能设置自己任课班级的课堂大屏', 'danger')
        return redirect(url_for('classroom.admin_classroom'))

    new_schedule_id = parse_int(schedule_id)
    if new_schedule_id is not None and not db.session.get(Schedule, new_schedule_id):
        flash('所选作息时段不存在', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    seat_offset_val = parse_int(seat_offset, 0)
    if not (0 <= seat_offset_val <= 254):
        flash('座位偏移需在 0-254 之间', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    auto_switch = request.form.get('auto_switch') == 'true'
    if is_admin and auto_switch:
        # 防呆（现场反馈）：非作息时段手工设置班级时若保留「课程表自动
        # 切换」，随后任何管理端大屏访问都会触发自动同步——目标班级集合
        # 为空，刚设置的班级被自动停用并清空（表现为“一刷新就变未设置”）。
        # 此时自动关闭自动切换并明确提示；处于作息时段则保持用户选择。
        if _auto_period_for_now(get_schedules_cached(), datetime.now()) is None:
            auto_switch = False
            flash('当前不在作息时段：已自动关闭「课程表自动切换班级」，'
                  '避免刚设置的班级被自动同步清空；如需按课程表切换，'
                  '请在对应时段重新开启。', 'warning')

    session = ClassroomSession.query.filter_by(class_id=new_class_id).first()
    if not session:
        session = ClassroomSession(class_id=new_class_id)
        db.session.add(session)
    session.schedule_id = new_schedule_id
    session.display_message = display_message
    session.seat_offset = seat_offset_val
    if is_admin:
        session.auto_switch = auto_switch
    session.is_active = True
    session.updated_at = datetime.now()

    if is_admin:
        # 旧单班字段继续同步，兼容尚未升级的调用路径
        setting.active_class_id = new_class_id
        setting.current_schedule_id = new_schedule_id
        setting.display_message = display_message
        setting.seat_offset = seat_offset_val
        setting.auto_switch = auto_switch
        setting.updated_at = datetime.now()
    db.session.commit()
    invalidate_active_class_cache()
    from app.utils import sse_bump as _sse_bump
    _sse_bump('classroom')
    flash('课堂设置已更新', 'success')
    return redirect(url_for('classroom.admin_classroom', class_id=new_class_id))


@classroom_bp.route('/admin/classroom/new_session', methods=['POST'])
@teacher_login_required
def new_classroom_session():
    """开启新的一课 — 清空指定班级（或全部上课班级）的签到/座位信息。

    教师仅能清空本人任课班级；管理员保持“不传 class_id 清空全部”的原语义。
    """
    allowed_class_ids = _classroom_scope_ids()
    is_admin = allowed_class_ids is None
    if is_admin:
        # 升级兼容：只有旧单班设置时先落成会话，确保“全部上课班级”包含它
        _ensure_legacy_session(_get_classroom_setting())
    class_id = parse_int(request.form.get('class_id', '').strip())
    if class_id and not is_admin and class_id not in allowed_class_ids:
        flash('只能操作自己任课班级的课堂大屏', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    if class_id:
        _clear_class_login(class_id)
        cls = db.session.get(Class, class_id)
        flash(f'已开启新的一课，{(cls.name if cls else "所选班级")}的签到和座位号已清空', 'success')
    else:
        sessions = _sessions_for_display(allowed_class_ids)
        for session in sessions:
            _clear_class_login(session.class_id)
        if sessions:
            flash('已清空所有上课班级的签到信息', 'success')
        else:
            flash('当前没有可清空的上课班级', 'warning')
    db.session.commit()
    invalidate_active_class_cache()
    from app.utils import sse_bump as _sse_bump
    _sse_bump('classroom')
    return redirect(url_for('classroom.admin_classroom',
                            class_id=class_id or None))


@classroom_bp.route('/admin/classroom/session/stop', methods=['POST'])
@teacher_login_required
def stop_classroom_session():
    """停用某个班级的课堂会话（多班场景下单独结束一个班）。

    教师仅能停用本人任课班级，且不改写管理员的全局默认班级。
    """
    allowed_class_ids = _classroom_scope_ids()
    is_admin = allowed_class_ids is None
    class_id = parse_int(request.form.get('class_id', '').strip())
    if not class_id:
        flash('请指定要停用的班级', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    if not is_admin and class_id not in allowed_class_ids:
        flash('只能操作自己任课班级的课堂大屏', 'danger')
        return redirect(url_for('classroom.admin_classroom'))
    target = ClassroomSession.query.filter_by(class_id=class_id).first()
    if not target or not target.is_active:
        flash('该班级当前没有进行中的课堂', 'warning')
        return redirect(url_for('classroom.admin_classroom'))
    target.is_active = False
    _clear_class_login(class_id)
    if is_admin:
        setting = _get_classroom_setting()
        if setting.active_class_id == class_id:
            remaining = ClassroomSession.query.filter_by(
                is_active=True).order_by(ClassroomSession.id).first()
            setting.active_class_id = remaining.class_id if remaining else None
            setting.current_schedule_id = remaining.schedule_id if remaining else None
    db.session.commit()
    invalidate_active_class_cache()
    from app.utils import sse_bump as _sse_bump
    _sse_bump('classroom')
    flash(f'已停用 {target.class_.name if target.class_ else "该班级"} 的课堂大屏', 'success')
    remaining = _sessions_for_display(allowed_class_ids)
    return redirect(url_for('classroom.admin_classroom',
                            class_id=remaining[0].class_id if remaining else None))


# ──────────────────────────────────────────────
#  大屏展示
# ──────────────────────────────────────────────


@classroom_bp.route('/admin/classroom')
@teacher_login_required
def admin_classroom():
    """课堂大屏展示页面（管理员全部班级；教师仅本人任课班级）"""
    setting = _get_classroom_setting()
    allowed_class_ids = _classroom_scope_ids()
    is_admin = allowed_class_ids is None
    classes = _classroom_scope_classes()
    schedules = get_schedules_cached()

    now = datetime.now()
    # 课程表自动切班是全局副作用（会激活/停用其他班级），仅管理员页面触发；
    # 教师大屏不改变其他班级的会话状态
    if is_admin and setting.auto_switch and \
            request.headers.get('Sec-Fetch-Site') != 'cross-site':
        with _active_class_switch_lock:
            _sync_auto_sessions(setting, now)

    auto_schedule = _auto_period_for_now(schedules, now)
    requested_class_id = parse_int(request.args.get('class_id', '').strip())
    if requested_class_id is not None and not is_admin and \
            requested_class_id not in allowed_class_ids:
        return '无权访问该班级', 403
    session = _select_session(setting, requested_class_id, allowed_class_ids)
    sessions = _sessions_for_display(allowed_class_ids)
    if session and not requested_class_id:
        requested_class_id = session.class_id

    # 当前选中班级/节次（多班大屏通过 ?class_id= 区分）
    active_class = session.active_class if session else None
    current_schedule = (session.current_schedule if session else None) or auto_schedule
    page_setting = session or (setting if is_admin else ClassroomSetting())
    # 防呆提示：自动切换开启但当前不在作息时段时，自动同步会清空手工
    # 设置的班级（现场反馈）；模板据此显示醒目预警。
    auto_switch_no_period = bool(is_admin and page_setting.auto_switch
                                 and not auto_schedule)

    # 当前班级的签到情况
    attendance_data = None
    if active_class:
        thirty_mins_ago = datetime.now() - timedelta(minutes=30)
        students = Student.query.filter_by(class_id=active_class.id).order_by(
            Student.student_number, Student.name).all()
        checked_in = sum(1 for s in students if _seen_at(s) and _seen_at(s) >= thirty_mins_ago)
        total = len(students)
        # 学生列表（含座位号）+ 重复座位检测
        attendance_students = []
        for s in students:
            seen_at = _seen_at(s)
            is_online = seen_at and seen_at >= thirty_mins_ago
            seat = _calc_seat(s.ip_address, page_setting.seat_offset or 0)
            attendance_students.append({
                'id': s.id, 'name': s.name, 'student_number': s.student_number,
                'seat_number': seat,
                'is_online': is_online,
                'login_time': seen_at,
                'ip_address': s.ip_address or '',
                'seat_conflict': False  # 先标记，下面检测
            })
        # 检测重复座位：同一座位号只保留最近登录的学生
        seat_groups = {}
        for st in attendance_students:
            sn = st['seat_number']
            if sn is not None:
                seat_groups.setdefault(sn, []).append(st)
        for sn, group in seat_groups.items():
            if len(group) > 1:
                # 按login_time降序排列，未登录（None）恒排最后。注意第一项必须是
                # "is not None"：此前写成 "is None" 配合 reverse=True 会把未登录者
                # 排到最前 → 保留"未登录占座"、把真正在线的学生误标冲突/离线。
                group.sort(key=lambda x: (x['login_time'] is not None, x['login_time'] or datetime.min), reverse=True)
                # 第一个（最近登录）保持原样，其余标记为冲突
                for st in group[1:]:
                    st['seat_conflict'] = True
                    st['is_online'] = False
        # 按座位号排序（None 恒排最后；座位号 0 是合法机位，不得当空值处理）
        attendance_students.sort(key=lambda x: (x['seat_number'] is None, x['seat_number'] if x['seat_number'] is not None else 0))

        attendance_data = {
            'checked_in': checked_in,
            'total': total,
            'rate': round(checked_in / total * 100, 1) if total > 0 else 0,
            'students': attendance_students
        }

    # 申诉列表（joinedload(student)：模板访问申诉学生姓名，消除 N+1）
    # 教师只看到本人任课班级学生的申诉，避免跨班泄露
    appeals_q = Appeal.query.options(
        joinedload(Appeal.student)
    ).filter_by(is_read=False)
    if not is_admin:
        if not allowed_class_ids:
            appeals_q = appeals_q.filter(db.false())
        else:
            appeals_q = appeals_q.join(
                Student, Appeal.student_id == Student.id).filter(
                Student.class_id.in_(allowed_class_ids))
    appeals_list = appeals_q.order_by(
        Appeal.create_time.desc()).limit(10).all()

    return render_template('admin_classroom.html',
                           setting=page_setting, classes=classes, schedules=schedules,
                           sessions=sessions, selected_class_id=requested_class_id,
                           active_class=active_class, current_schedule=current_schedule,
                           attendance_data=attendance_data, now=now, auto_schedule=auto_schedule,
                           auto_switch_no_period=auto_switch_no_period,
                           appeals=appeals_list)


# ──────────────────────────────────────────────
#  JSON API
# ──────────────────────────────────────────────


@classroom_bp.route('/api/classroom/status', methods=['POST'])
# 注意：状态接口可能触发自动换班/清理登录态（写库副作用），须用 POST 而非 GET，
# 避免爬虫/预取在 GET 时意外执行写操作
@teacher_login_required
def api_classroom_status():
    """获取课堂实时状态 — 供大屏 AJAX 刷新（教师仅本人任课班级）"""
    setting = _get_classroom_setting()
    allowed_class_ids = _classroom_scope_ids()
    is_admin = allowed_class_ids is None

    now = datetime.now()
    current_time = now.strftime('%H:%M:%S')
    current_date = now.strftime('%Y年%m月%d日')
    weekday = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'][now.weekday()]

    schedules = get_schedules_cached()
    schedule_list = [{
        'id': s.id, 'period_name': s.period_name,
        'start_time': s.start_time, 'end_time': s.end_time
    } for s in schedules]

    # 自动判断当前节次；课程表切班提前 5 分钟
    auto_schedule = _auto_period_for_now(schedules, now)
    auto_period = None
    if auto_schedule:
        auto_period = {'id': auto_schedule.id, 'period_name': auto_schedule.period_name,
                       'start_time': auto_schedule.start_time,
                       'end_time': auto_schedule.end_time}

    # 下一节课
    next_period = None
    if auto_period:
        for s in schedules:
            if s.start_time > auto_period['end_time']:
                next_period = {'id': s.id, 'period_name': s.period_name,
                               'start_time': s.start_time, 'end_time': s.end_time}
                break

    # 当前节次倒计时
    countdown_seconds = None
    if auto_period:
        try:
            end_h, end_m = map(int, auto_period['end_time'].split(':'))
            end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
            diff = (end_dt - now).total_seconds()
            countdown_seconds = max(0, int(diff))
        except (ValueError, TypeError):
            current_app.logger.debug('Failed to parse period end_time for countdown')
            countdown_seconds = 0

    # ── 课程表自动切换：按课表行批量激活多个班级会话 ──
    # 全局副作用仅管理员触发；教师状态轮询不改动其他班级会话
    if is_admin and setting.auto_switch and \
            request.headers.get('Sec-Fetch-Site') != 'cross-site':
        with _active_class_switch_lock:
            _sync_auto_sessions(setting, now)

    requested_class_id = parse_int((request.form.get('class_id')
                                    or request.args.get('class_id') or '').strip())
    if requested_class_id is not None and not is_admin and \
            requested_class_id not in allowed_class_ids:
        return jsonify({'success': False, 'msg': '无权访问该班级'}), 403
    page_session = _select_session(setting, requested_class_id, allowed_class_ids)
    if page_session and not requested_class_id:
        requested_class_id = page_session.class_id

    # 当前上课班级
    active_class_data = None
    attendance_summary = None
    attendance_students = []
    if page_session and page_session.active_class:
        ac = page_session.active_class
        thirty_mins_ago = now - timedelta(minutes=30)
        # 列裁剪：大屏 10s 轮询热路径，此前加载含 password_hash 的全列
        # （250 人 = 250 行全列每 10s 一次传输）
        students = Student.query.with_entities(
            Student.id, Student.name, Student.student_number,
            Student.ip_address, Student.last_seen, Student.login_time
        ).filter_by(class_id=ac.id).order_by(
            Student.student_number, Student.name).all()
        checked_in = sum(1 for s in students if _seen_at(s) and _seen_at(s) >= thirty_mins_ago)
        total = len(students)
        active_class_data = {'id': ac.id, 'name': ac.name}
        attendance_summary = {
            'checked_in': checked_in,
            'total': total,
            'rate': round(checked_in / total * 100, 1) if total > 0 else 0
        }
        # 学生座位号列表 + 重复座位检测
        for s in students:
            seen_at = _seen_at(s)
            is_online = seen_at and seen_at >= thirty_mins_ago
            seat = _calc_seat(s.ip_address, page_session.seat_offset or 0)
            attendance_students.append({
                'id': s.id, 'name': s.name, 'student_number': s.student_number,
                'seat_number': seat,
                'is_online': is_online,
                'login_time': seen_at.strftime('%H:%M:%S') if seen_at else None,
                'ip_address': s.ip_address or '',
                'seat_conflict': False
            })
        # 检测重复座位
        seat_groups = {}
        for st in attendance_students:
            sn = st['seat_number']
            if sn is not None:
                seat_groups.setdefault(sn, []).append(st)
        for sn, group in seat_groups.items():
            if len(group) > 1:
                # 同 L663：未登录（None）恒排最后，在线/最近登录者保留占座
                group.sort(key=lambda x: (x['login_time'] is not None, x['login_time'] or ''), reverse=True)
                for st in group[1:]:
                    st['seat_conflict'] = True
                    st['is_online'] = False

    # 选中节次（每个班级会话可独立；未设置时回退自动检测）
    selected_schedule = None
    if page_session and page_session.current_schedule:
        cs = page_session.current_schedule
        selected_schedule = {'id': cs.id, 'period_name': cs.period_name,
                             'start_time': cs.start_time, 'end_time': cs.end_time}
    if not selected_schedule:
        selected_schedule = auto_period

    appeals_q = Appeal.query.options(joinedload(Appeal.student)).filter_by(
        is_read=False)
    if not is_admin:
        if not allowed_class_ids:
            appeals_q = appeals_q.filter(db.false())
        else:
            appeals_q = appeals_q.join(
                Student, Appeal.student_id == Student.id).filter(
                Student.class_id.in_(allowed_class_ids))
    appeals = appeals_q.order_by(Appeal.create_time.desc()).limit(10).all()

    return jsonify({
        'success': True,
        'data': {
            'current_time': current_time,
            'current_date': current_date,
            'weekday': weekday,
            'schedules': schedule_list,
            'auto_period': auto_period,
            'next_period': next_period,
            'selected_schedule': selected_schedule,
            'countdown_seconds': countdown_seconds,
            'active_class': active_class_data,
            'sessions': [{'id': s.id, 'class_id': s.class_id,
                          'class_name': s.class_.name if s.class_ else ''}
                         for s in _sessions_for_display(allowed_class_ids)],
            'attendance': attendance_summary,
            'attendance_students': attendance_students,
            'seat_offset': page_session.seat_offset if page_session else 0,
            'display_message': page_session.display_message if page_session else '',
            'appeals': [{
                'id': a.id,
                'student_name': a.student.name if a.student else '未知',
                'message': a.message,
                'time': a.create_time.strftime('%H:%M:%S') if a.create_time else '',
                'is_read': a.is_read
            } for a in appeals]
        }
    })


@classroom_bp.route('/api/schedule')
def api_schedule():
    """获取作息时间表JSON — 供登录页使用"""
    schedules = get_schedules_cached()
    return jsonify({
        'success': True,
        'data': [{
            'id': s.id, 'period_name': s.period_name,
            'start_time': s.start_time, 'end_time': s.end_time
        } for s in schedules]
    })
