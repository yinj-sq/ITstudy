"""每日签到记录服务。

签到语义：学生登录/活跃即视为当天签到，且仅在签到时间窗口内
（SystemConfig.attendance_time_window，默认 07:00-22:00）计为"窗口内到课"。
- record_student_login：登录成功时 upsert 当天记录（窗口内 → online）
- update_student_last_seen：心跳时更新当天记录 last_seen（窗口内 → online）
- get_history / export_history：按日期+班级查询/导出，缺失学生懒补全为 offline
"""
import logging
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.utils import excel_safe

logger = logging.getLogger(__name__)


def _seat_number(student, offset):
    """按 IP 末段计算座位号（与 api.py _calc_seat 一致）。

    结果 < 1（IP 末段小于偏移量）视为无效返回 None，避免签到记录
    出现 0/负座位号。
    """
    try:
        ip = student.ip_address or ''
        seat = int(ip.split('.')[-1]) - int(offset or 0)
    except (ValueError, IndexError):
        return None
    return seat if seat >= 1 else None


def _parse_time_window(value):
    """解析签到时间窗口配置 "HH:MM-HH:MM"；解析失败返回 None。

    None 表示"无有效窗口"，调用方按窗口内处理（fail-open，考勤不误伤）。
    """
    if not value or not isinstance(value, str):
        return None
    try:
        from datetime import time as _time
        start_s, end_s = value.split('-', 1)
        return (_time.fromisoformat(start_s.strip()),
                _time.fromisoformat(end_s.strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def _now_within_window():
    """当前本地时间是否处于签到时间窗口内。

    语义：窗口外登录不代表缺勤，仅不计为"窗口内到课"。
    配置缺失/解析失败时按窗口内处理（fail-open，考勤不误伤学生）。
    支持跨天窗口（如 "22:00-06:00"）。
    """
    from app.models import SystemConfig
    try:
        window = _parse_time_window(
            SystemConfig.get('attendance_time_window', '07:00-22:00'))
    except Exception:
        return True
    if window is None:
        return True
    start, end = window
    now = datetime.now().time()
    if start <= end:
        return start <= now <= end
    # 跨天窗口（开始时间 > 结束时间）
    return now >= start or now <= end


def record_student_login(student):
    """学生登录成功 → upsert 当天签到记录。

    签到时间窗口语义（SystemConfig.attendance_time_window，默认 07:00-22:00）：
    - 窗口内登录 → 记录 status='online'（计为"窗口内到课"）
    - 窗口外登录 → 仅当当天记录不存在时创建 status='offline' 记录；
      不把已有 online 记录降级（窗口外登录不代表缺勤，仅不计为"窗口内到课"）
    - 时间配置解析失败/异常 → 按窗口内处理（fail-open，考勤不误伤）
    """
    from app.models import AttendanceRecord
    today = date.today()
    if not student.class_id:
        return
    within = _now_within_window()
    try:
        rec = AttendanceRecord.query.filter_by(
            record_date=today, class_id=student.class_id,
            student_id=student.id).first()
        if rec:
            # 窗口内心跳/登录确认到课；窗口外保持原状态（不降级）
            if within and rec.status != 'online':
                rec.status = 'online'
            rec.name = student.name
            rec.login_time = student.login_time
            rec.last_seen = student.last_seen
        else:
            from app.models import ClassroomSetting
            setting = ClassroomSetting.query.first()
            rec = AttendanceRecord(
                record_date=today, class_id=student.class_id,
                student_id=student.id, name=student.name,
                status='online' if within else 'offline',
                login_time=student.login_time, last_seen=student.last_seen,
                seat_number=_seat_number(student, setting.seat_offset if setting else 0))
            db.session.add(rec)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.debug('写入签到记录失败（已忽略）', exc_info=True)


def update_student_last_seen(student):
    """心跳 → 更新当天签到记录 last_seen。

    窗口内心跳会把记录置为 online（确认"窗口内到课"）；窗口外心跳仅更新
    last_seen，不改变已有状态（不降级）。
    """
    from app.models import AttendanceRecord
    today = date.today()
    if not student.class_id:
        return
    within = _now_within_window()
    try:
        rec = AttendanceRecord.query.filter_by(
            record_date=today, class_id=student.class_id,
            student_id=student.id).first()
        if rec:
            rec.last_seen = student.last_seen
            if within and rec.status != 'online':
                rec.status = 'online'
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.debug('更新签到记录 last_seen 失败（已忽略）', exc_info=True)


def _backfill_offline(record_date, class_id, student_ids):
    """懒补全：为该 (date, class_id) 缺失的学生补 offline 记录。"""
    from app.models import AttendanceRecord, ClassroomSetting
    existing = {
        r.student_id for r in AttendanceRecord.query.filter_by(
            record_date=record_date, class_id=class_id).all()
    }
    missing = [sid for sid in student_ids if sid not in existing]
    if not missing:
        return
    from app.models import Student
    students = {s.id: s for s in Student.query.filter(Student.id.in_(missing)).all()}
    setting = ClassroomSetting.query.first()
    added = []
    for sid in missing:
        s = students.get(sid)
        if not s:
            continue
        added.append(AttendanceRecord(
            record_date=record_date, class_id=class_id, student_id=sid,
            name=s.name, status='offline',
            seat_number=_seat_number(s, setting.seat_offset if setting else 0)))
    if added:
        db.session.add_all(added)
        try:
            db.session.commit()
            logger.info('签到记录懒补全: date=%s class=%s 补 %d 条 offline',
                        record_date, class_id, len(added))
        except IntegrityError:
            # 两名管理员并发查询同班同日历史时，双方都发现缺员并插入，
            # 后提交方撞唯一约束 uq(record_date, class_id, student_id)。
            # 补全仅为加速查询，冲突可安全忽略——回滚后按已有记录返回
            db.session.rollback()
            logger.debug('签到懒补全并发冲突（已忽略）: date=%s class=%s',
                         record_date, class_id)


def get_history(record_date, class_id):
    """按日期+班级查询签到记录（缺失学生懒补全为 offline）。

    Returns:
        (records, stats): 记录列表（按座位号/姓名排序）、{'total', 'online', 'offline'}
    """
    from app.models import AttendanceRecord, Student
    cid = int(class_id)
    # 该班当前学生
    students = Student.query.filter_by(class_id=cid).order_by(
        Student.student_number, Student.name).all()
    if not students:
        return [], {'total': 0, 'online': 0, 'offline': 0}
    # 懒补全仅限当天：历史日期用「当前班级名册」补 offline 会给后来入班的
    # 学生伪造过去缺勤记录，转出学生的旧记录也会被错误计入当前名册统计。
    from datetime import date as _date
    if record_date == _date.today():
        _backfill_offline(record_date, cid, [s.id for s in students])

    records = AttendanceRecord.query.filter_by(
        record_date=record_date, class_id=cid).all()
    records.sort(key=lambda r: (r.seat_number is None, r.seat_number or 0, r.name))
    stats = {
        'total': len(records),
        'online': sum(1 for r in records if r.status == 'online'),
        'offline': sum(1 for r in records if r.status == 'offline'),
    }
    return records, stats


def export_history(record_date, class_id, class_name):
    """导出指定日期+班级的签到记录为 Excel 字节流。"""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    records, stats = get_history(record_date, class_id)

    wb = Workbook()
    ws = wb.active
    ws.title = f'{record_date} 签到'
    ws.append([f'{excel_safe(class_name)} 签到记录（{record_date}）'])
    ws.merge_cells('A1:H1')
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')
    ws.append([f'应到 {stats["total"]} 人 | 已签到 {stats["online"]} 人 | 未签到 {stats["offline"]} 人'])
    ws.merge_cells('A2:H2')
    ws.append([])
    headers = ['序号', '学号', '姓名', '签到状态', '签到时间', '最后活跃', '座位号']
    ws.append(headers)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        cell.alignment = Alignment(horizontal='center')

    from app.models import Student
    sid_map = {s.id: s for s in
               Student.query.filter(Student.id.in_([r.student_id for r in records])).all()}
    for idx, r in enumerate(records, 1):
        stu = sid_map.get(r.student_id)
        ws.append([
            idx,
            excel_safe(stu.student_number if stu else ''),
            excel_safe(r.name),
            '已签到' if r.status == 'online' else '未签到',
            r.login_time.strftime('%Y-%m-%d %H:%M:%S') if r.login_time else '',
            r.last_seen.strftime('%Y-%m-%d %H:%M:%S') if r.last_seen else '',
            r.seat_number if r.seat_number is not None else '',
        ])
        if r.status == 'offline':
            for col in range(1, 8):
                ws.cell(row=4 + idx, column=col).fill = \
                    PatternFill(start_color='FDE9E9', end_color='FDE9E9', fill_type='solid')
    for col, w in zip('ABCDEFG', [6, 12, 10, 10, 20, 20, 8]):
        ws.column_dimensions[col].width = w

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
