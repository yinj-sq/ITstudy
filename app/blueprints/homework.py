from flask import Blueprint, request, render_template, redirect, url_for, session, flash, jsonify, send_file
from flask import current_app
from datetime import datetime
import os
import json
import re
import shutil
import uuid
from io import BytesIO
from app.extensions import db
from sqlalchemy import or_, text
from sqlalchemy import func as _func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from app.models import Homework, HomeworkSubmission, Class, Student, homework_classes
from app.decorators import admin_login_required, login_required, teacher_login_required
from app.services.download_pool import send_large_download
from app.services.resource_access import (
    teacher_class_ids, teacher_classes, teacher_subject_ids, teacher_subjects)
from app.utils import (
    secure_filename_with_unicode, get_classes_cached, get_subjects_cached,
    safe_inline_mimetype, parse_int, send_temp_zip,
)

homework_bp = Blueprint('homework', __name__, url_prefix='')

# 作业附件存储目录（使用绝对路径，避免工作目录不同导致文件找不到）
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOMEWORK_DIR = os.path.join(_BASE, 'static', 'homework')
SUBMISSION_DIR = os.path.join(_BASE, 'static', 'submissions')

# 等级评分列表
GRADE_LEVELS = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'D', 'E']

# 作业附件上传限制：拒绝危险可执行/脚本扩展名，防止恶意文件借作业链路分发
_HOMEWORK_REJECT_EXTS = {
    'exe', 'bat', 'cmd', 'com', 'scr', 'vbs', 'js', 'jse', 'html', 'htm',
    'svg', 'msi', 'ps1', 'dll', 'sh', 'php', 'asp', 'aspx', 'jsp', 'jar',
    'apk', 'msix', 'iso', 'reg',
}
MAX_TEACHER_ATTACH_MB = 100   # 教师发布作业附件单文件上限
MAX_STUDENT_ATTACH_MB = 50    # 学生提交附件单文件上限
# 学生提交聚合上限：单文件 50MB 且每次请求最多 200MB（全局），若只限单文件，
# 反复重交会无限追加旧附件（每次新文件全部保留），任一学生可耗尽磁盘。
MAX_STUDENT_SUBMIT_MB = 100         # 单次请求新上传总量
MAX_SUBMISSION_TOTAL_MB = 200       # 单份提交（含历史重交附件）累计总量
MAX_SUBMISSION_FILES = 20           # 单份提交文件数上限


def _dir_size_bytes(path):
    total = 0
    try:
        for name in os.listdir(path):
            p = os.path.join(path, name)
            if os.path.isfile(p):
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files):
    """清理本次请求新写入、且不在原记录中的文件（不误删旧附件）。"""
    if os.path.basename(sub_dir).startswith('tmp_'):
        shutil.rmtree(sub_dir, ignore_errors=True)
        return
    for name in uploaded_files:
        if name in old_record_files:
            continue
        try:
            os.remove(os.path.join(sub_dir, name))
        except OSError:
            pass


def _save_homework_attachment(file_storage, target_dir, max_mb, field_label='附件',
                              overwrite=False):
    """校验并保存作业附件：拒绝危险扩展名 + 单文件大小上限。

    返回 (ok, message, filename)；ok=False 时未写入任何文件。
    overwrite=True 时同名文件原子替换（学生重交改正版）；默认拒绝同名。
    流式落盘（file_storage.save 直写磁盘）后按 getsize 实测校验——
    此前 read(max+1) 把整个文件读入内存后才判定，50-100MB 附件在
    并发提交下内存峰值 ≈ 并发数×文件大小（其余上传点均已流式化，
    仅此链路漏网）；content_length 可被伪造，落盘后实测是唯一可靠口径。
    """
    if not file_storage or not file_storage.filename:
        return True, '', None
    fname = secure_filename_with_unicode(file_storage.filename)
    # 归一化尾点/尾空白：Windows 文件系统会剥离尾点（'a.exe.' 落盘为真实
    # 'a.exe'），黑名单扩展名校验在归一化后进行，防止黑名单被尾点绕过
    fname = fname.rstrip('. ')
    if not fname:
        return False, f'{field_label}「{file_storage.filename}」文件名无效', None
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    # 双重校验：归一化后文件名 + 原始文件名（防 secure_filename 清洗形态差异）
    raw_ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext in _HOMEWORK_REJECT_EXTS or raw_ext in _HOMEWORK_REJECT_EXTS:
        return False, f'{field_label}「{file_storage.filename}」为禁止上传的文件类型', None
    max_size = max_mb * 1024 * 1024
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, fname)
    # 同名冲突拒绝（此前静默覆盖：同一作业上传两个同名附件时后者顶掉
    # 前者，且 attachments JSON 出现两条指向同一磁盘文件的记录）。
    # 学生重交例外：改正后的同名文件必须能替换旧版（记录按文件名去重）
    if not overwrite and os.path.exists(target_path):
        return False, (f'{field_label}「{fname}」已存在同名附件，'
                       '请重命名后再上传'), None
    # 先写 .part 临时文件、校验通过后原子改名到位：
    # 1) 超限/空文件不再先全量落盘真实文件名（校验失败即删 .part，
    #    消除"校验前同名附件短暂可见/半成品可下载"窗口与并发覆盖 TOCTOU）
    # 2) 请求中途断开残留 .part 也不会顶掉后续合法上传
    part_path = target_path + '.part'
    try:
        file_storage.save(part_path)
    except Exception:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return False, f'{field_label}「{file_storage.filename}」文件保存失败', None

    def _discard():
        try:
            os.remove(part_path)
        except OSError:
            pass

    size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    if size > max_size:
        _discard()
        return False, f'{field_label}「{file_storage.filename}」超过 {max_mb}MB 上限', None
    if size == 0:
        # 0 字节文件拒绝（此前缺陷：记录入档但不落盘 → "幽灵附件"
        # 学生/教师下载 404，作业列表却显示该附件）
        _discard()
        return False, f'{field_label}「{file_storage.filename}」文件内容为空', None
    try:
        os.replace(part_path, target_path)
    except OSError:
        _discard()
        return False, f'{field_label}「{file_storage.filename}」文件保存失败', None
    return True, '', fname


def _ensure_dirs():
    os.makedirs(HOMEWORK_DIR, exist_ok=True)
    os.makedirs(SUBMISSION_DIR, exist_ok=True)


def _safe_file_under(base_dir, relative_path):
    """返回位于 base_dir 内的文件路径；非法路径返回 None。"""
    safe_rel = (relative_path or '').replace('\\', '/').lstrip('/')
    if not safe_rel or '..' in safe_rel.split('/'):
        return None
    base_real = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base_real, safe_rel))
    if target == base_real or not target.startswith(base_real + os.sep):
        return None
    return target


def _student_can_access_homework(hw, student_id):
    student = db.session.get(Student, student_id)
    return bool(
        student and student.class_id and
        hw.classes.filter(Class.id == student.class_id).first()
    )


def _teacher_can_manage_homework(hw):
    """作业归属校验（教师数据边界）：
    - 管理员（is_admin）全部可管理；
    - 教师必须是该作业的创建者，或作业为管理员创建（teacher_id=None），
      且作业至少分配到教师所属的一个班级；无班级归属的教师无权限。
    """
    if session.get('is_admin'):
        return True
    tid = session.get('teacher_id')
    if not tid or getattr(hw, 'teacher_id', None) not in (None, tid):
        return False
    class_ids = teacher_class_ids(tid)
    if not class_ids:
        return False
    return hw.classes.filter(Class.id.in_(class_ids)).first() is not None


def _homework_teacher_scope():
    """当前教师可操作的班级/学科范围；管理员返回 (None, None)。"""
    if session.get('is_admin'):
        return None, None
    tid = session.get('teacher_id')
    return teacher_class_ids(tid), teacher_subject_ids(tid)


def _teacher_scope_class_ids():
    """当前教师可访问的班级集合；管理员返回 None。"""
    if session.get('is_admin'):
        return None
    return teacher_class_ids(session.get('teacher_id'))


def _teacher_can_access_submission(sub):
    """提交记录的数据边界：教师只能访问本人任课班级学生的提交。"""
    if session.get('is_admin'):
        return True
    class_ids = teacher_class_ids(session.get('teacher_id'))
    student = sub.student or db.session.get(Student, sub.student_id)
    return bool(class_ids and student and student.class_id in class_ids)


def _teacher_can_edit_homework(hw):
    """整份作业的编辑/删除权限：管理员或作业创建教师。

    管理员创建的多班作业可由各任课教师批改本人班级提交，但整份作业的
    标题/截止时间/删除会影响所有班，不能让任一任课教师单独修改。
    """
    if session.get('is_admin'):
        return True
    tid = session.get('teacher_id')
    if not tid or getattr(hw, 'teacher_id', None) != tid:
        return False
    if not _teacher_can_manage_homework(hw):
        return False
    # 教师创建者也只能在整份作业都仍属于本人任课班级时编辑/删除；
    # 管理员后来把作业扩展到其他班时，避免教师单方面影响其他班。
    class_ids = teacher_class_ids(tid)
    hw_class_ids = {c.id for c in hw.classes.all()}
    return bool(class_ids and hw_class_ids and hw_class_ids.issubset(class_ids))




# ═══════════════════════════════════════════════════════════════
#  教师端：作业管理
# ═══════════════════════════════════════════════════════════════

@homework_bp.route('/admin/homework')
@teacher_login_required
def admin_homework():
    """教师端作业列表"""
    from sqlalchemy.orm import joinedload
    from app.utils import paginate_query
    from app.services.delivery_worker import get_active_deliveries
    active_deliveries = get_active_deliveries()
    # subject 普通关系 eager load；classes 是 dynamic 关系无法 eager load，
    # 改为批量预加载 homework→班级名 映射，消除模板逐行查询；
    # 分页渲染，避免作业增长后单页全量加载
    query = Homework.query.options(joinedload(Homework.subject))
    scope_class_ids, _ = _homework_teacher_scope()
    if not session.get('is_admin'):
        # 教师数据边界：本人/管理员创建，且作业至少覆盖本人任课班级
        query = query.filter(or_(
            Homework.teacher_id == session.get('teacher_id'),
            Homework.teacher_id.is_(None),
        ))
        if scope_class_ids:
            hw_scope_ids = db.session.query(homework_classes.c.homework_id).filter(
                homework_classes.c.class_id.in_(scope_class_ids))
            query = query.filter(Homework.id.in_(hw_scope_ids))
        else:
            query = query.filter(db.false())
    pagination = paginate_query(
        query.order_by(Homework.create_time.desc()),
        default_per_page=20, max_per_page=100
    )
    homeworks = pagination.items
    if session.get('is_admin'):
        subjects = get_subjects_cached()
        classes = get_classes_cached()
    else:
        subjects = teacher_subjects(session.get('teacher_id'))
        classes = teacher_classes(session.get('teacher_id'))

    # 统计每个作业的提交/未批改数量（单次查询；教师只统计本人班级的学生）
    from sqlalchemy import func, case
    hw_stats = {}
    hw_class_names = {}
    hw_class_ids_map = {}
    if homeworks:
        hw_ids = [hw.id for hw in homeworks]
        stats_query = db.session.query(
            HomeworkSubmission.homework_id,
            func.count(HomeworkSubmission.id).label('total'),
            func.sum(case((HomeworkSubmission.status == 'submitted', 1), else_=0)).label('ungraded')
        )
        if scope_class_ids is not None:
            stats_query = stats_query.join(
                Student, Student.id == HomeworkSubmission.student_id).filter(
                Student.class_id.in_(scope_class_ids))
        stats_rows = stats_query.filter(
            HomeworkSubmission.homework_id.in_(hw_ids)
        ).group_by(HomeworkSubmission.homework_id).all()
        hw_stats = {row.homework_id: {'total': row.total, 'ungraded': row.ungraded or 0} for row in stats_rows}
        for hw in homeworks:
            if hw.id not in hw_stats:
                hw_stats[hw.id] = {'total': 0, 'ungraded': 0}
        # 批量加载作业-班级关系（一次查询 homework_classes 关联表）
        rel_rows = db.session.execute(
            homework_classes.select().where(
                homework_classes.c.homework_id.in_(hw_ids))
        ).all()
        if rel_rows:
            cls_ids = {r[1] for r in rel_rows}
            if scope_class_ids is not None:
                cls_ids &= scope_class_ids
            cls_map = {c.id: c.name for c in
                       Class.query.filter(Class.id.in_(cls_ids)).all()}
            for hw_id, cls_id in rel_rows:
                hw_class_ids_map.setdefault(hw_id, set()).add(cls_id)
                if cls_id not in cls_map:
                    continue
                hw_class_names.setdefault(hw_id, []).append(cls_map.get(cls_id, ''))

    # 可编辑作业 id：一次按已加载的班级映射判定，替代逐行
    # _teacher_can_edit_homework 的 teacher_class_ids + classes 查询
    # （20 行约 80 次 SQL → 0 次）
    if session.get('is_admin'):
        editable_ids = {hw.id for hw in homeworks}
    else:
        tid = session.get('teacher_id')
        editable_ids = {
            hw.id for hw in homeworks
            if tid and hw.teacher_id == tid
            and hw_class_ids_map.get(hw.id)
            and hw_class_ids_map[hw.id].issubset(scope_class_ids or set())
        }

    return render_template('admin_homework.html', homeworks=homeworks,
                           subjects=subjects, classes=classes, hw_stats=hw_stats,
                           grade_levels=GRADE_LEVELS, hw_class_names=hw_class_names,
                           editable_homework_ids=editable_ids,
                           pagination=pagination,
                           active_deliveries=active_deliveries)


@homework_bp.route('/admin/homework/delivery-progress/active')
@teacher_login_required
def delivery_progress_active():
    """进行中的附件投递列表（供列表页轮询进度条）"""
    from app.services.delivery_worker import get_active_deliveries
    active = get_active_deliveries()
    if not session.get('is_admin'):
        # 教师数据边界：仅保留本人可管理的作业投递记录
        tid = session.get('teacher_id')
        owned = {row[0] for row in Homework.query.with_entities(Homework.id).filter(
            or_(Homework.teacher_id == tid, Homework.teacher_id.is_(None))).all()}
        active = [d for d in active if not d.get('hw_id') or d['hw_id'] in owned]
    # 补充作业标题
    from app.models import Homework as _HW
    titles = {}
    hw_ids = [d.get('hw_id') for d in active if d.get('hw_id')]
    if hw_ids:
        titles = {h.id: h.title for h in _HW.query.filter(_HW.id.in_(hw_ids)).all()}
    for d in active:
        d['title'] = titles.get(d.get('hw_id'), '作业')
    return jsonify({'success': True, 'data': active})


@homework_bp.route('/admin/homework/delivery-progress/<int:hw_id>')
@teacher_login_required
def delivery_progress_detail(hw_id):
    """单个作业的投递进度/结果详情（含容量不足名单）"""
    hw = db.session.get(Homework, hw_id)
    if hw and not _teacher_can_manage_homework(hw):
        return jsonify({'success': False, 'message': '无权查看'}), 403
    from app.services.delivery_worker import get_delivery_progress
    rec = get_delivery_progress(hw_id)
    if not rec:
        return jsonify({'success': False, 'message': '无投递记录'}), 404
    if not session.get('is_admin'):
        # 投递结果含学生姓名/班级；教师只看本人任课班级的名单
        rec = dict(rec)
        allowed_names = {c.name for c in teacher_classes(session.get('teacher_id'))}
        for key in ('insufficient', 'failed'):
            rows = rec.get(key)
            if isinstance(rows, list):
                rec[key] = [row for row in rows
                            if isinstance(row, dict)
                            and row.get('class') in allowed_names]
    return jsonify({'success': True, 'data': rec})


@homework_bp.route('/admin/homework/create', methods=['GET', 'POST'])
@teacher_login_required
def admin_homework_create():
    """教师创建作业"""
    _ensure_dirs()
    scope_class_ids, scope_subject_ids = _homework_teacher_scope()
    if request.method == 'POST':
        # 标题剥离 HTML 标签（纵深防御：投递进度条等 innerHTML 拼接面
        # 已做转义，入库前剥离标签字符防其它渲染面触发存储型 XSS）
        title = re.sub(r'<[^>]*>', '', request.form.get('title', '').strip())
        description = request.form.get('description', '').strip()
        subject_id = request.form.get('subject_id', '').strip()
        deadline_str = request.form.get('deadline', '').strip()
        class_ids = request.form.getlist('class_ids')

        if not title:
            flash('作业标题不能为空')
            return redirect(url_for('homework.admin_homework_create'))

        # 未选班级拒绝发布（此前静默容忍：无班级的作业发布后任何学生
        # 都看不到，管理员误以为已发布成功）
        if not class_ids:
            flash('请至少选择一个接收班级', 'danger')
            return redirect(url_for('homework.admin_homework_create'))
        if scope_class_ids is not None:
            chosen = {parse_int(c) for c in class_ids if str(c).strip().isdigit()}
            if not chosen or not chosen.issubset(scope_class_ids):
                flash('只能给自己任课的班级发布作业', 'danger')
                return redirect(url_for('homework.admin_homework_create'))
            sid = parse_int(subject_id)
            if sid is not None and sid not in scope_subject_ids:
                flash('只能选择自己所属学科的作业', 'danger')
                return redirect(url_for('homework.admin_homework_create'))

        try:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M') if deadline_str else None
        except ValueError:
            flash('截止日期格式不正确，请使用正确的日期格式')
            return redirect(url_for('homework.admin_homework'))
        sid = int(subject_id) if subject_id else None
        # 记录创建者（Teacher.id；管理员创建时无 teacher_id 则为 None）。
        # 旧版 FK 曾错误指向 student 表导致无法写入，现已改为普通整数列。
        teacher_id = session.get('teacher_id') or None

        hw = Homework(title=title, description=description, subject_id=sid,
                       attachments=json.dumps([], ensure_ascii=False),
                       deadline=deadline, teacher_id=teacher_id)

        db.session.add(hw)
        db.session.flush()  # 先落库获取 hw.id，附件目录按 id 命名

        # 附件目录：/static/homework/<hw_id>/（此前按标题命名——同名作业
        # 共用目录互覆盖、删除互相摧毁；id 唯一且不可变，标题修改不影响）
        hw_dir = os.path.join(HOMEWORK_DIR, str(hw.id))
        os.makedirs(hw_dir, exist_ok=True)
        attachments = []
        try:
            for field_name in ['files', 'attachments']:
                if field_name in request.files:
                    files = request.files.getlist(field_name)
                    for f in files:
                        ok, msg, fname = _save_homework_attachment(
                            f, hw_dir, MAX_TEACHER_ATTACH_MB, '作业附件')
                        if not ok:
                            flash(msg, 'danger')
                            db.session.rollback()
                            shutil.rmtree(hw_dir, ignore_errors=True)
                            return redirect(url_for('homework.admin_homework_create'))
                        if fname:
                            attachments.append(fname)
        except Exception:
            db.session.rollback()
            shutil.rmtree(hw_dir, ignore_errors=True)
            raise
        hw.attachments = json.dumps(attachments, ensure_ascii=False)

        # 关联班级
        if class_ids:
            for cid in class_ids:
                cls = db.session.get(Class, parse_int(cid))
                if cls:
                    hw.classes.append(cls)

        try:
            db.session.commit()
        except Exception:
            # 新建作业提交失败：DB 回滚后 hw 行不存在，已写入的附件目录
            # 成为孤儿；逐个删除本次写入文件并尽力移除空目录。
            db.session.rollback()
            for name in attachments:
                fp = _safe_file_under(hw_dir, name)
                try:
                    if fp and os.path.isfile(fp):
                        os.remove(fp)
                except OSError:
                    pass
            try:
                os.rmdir(hw_dir)
            except OSError:
                pass
            current_app.logger.warning('新建作业提交失败，已回收附件', exc_info=True)
            flash('作业发布失败，请重试', 'danger')
            return redirect(url_for('homework.admin_homework_create'))
        # 清除受保护静态目录鉴权用的 id 映射缓存
        from app.extensions import cache as _hw_cache
        for _c in hw.classes.all():
            _hw_cache.delete(f'homework:allowed_ids:{_c.id}')
        if request.form.get('deliver_to_drive') == '1':
            # 后台线程投递 + 前端进度条（数百名学生时不再阻塞页面）
            from app.services.delivery_worker import (
                start_homework_delivery, register_active)
            sender_name = session.get('teacher_name') or '管理员'
            start_homework_delivery(current_app._get_current_object(),
                                    hw.id, hw_dir, sender_name=sender_name)
            register_active(hw.id)
            flash(f'作业 "{title}" 已发布，正在投递附件到学生个人网盘…（可在作业列表查看进度）')
        else:
            flash(f'作业 "{title}" 已发布')
        return redirect(url_for('homework.admin_homework'))

    subjects = teacher_subjects(session.get('teacher_id')) if scope_class_ids is not None \
        else get_subjects_cached()
    classes = teacher_classes(session.get('teacher_id')) if scope_class_ids is not None \
        else get_classes_cached()
    return render_template('admin_homework_create.html',
                           subjects=subjects, classes=classes)


@homework_bp.route('/admin/homework/<int:hw_id>/edit', methods=['GET', 'POST'])
@teacher_login_required
def admin_homework_edit(hw_id):
    """教师编辑作业"""
    hw = db.get_or_404(Homework, hw_id)
    if not _teacher_can_edit_homework(hw):
        flash('只有管理员或作业创建教师可以编辑该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    if request.method == 'POST':
        # 与创建路径一致：标题剥离 HTML 标签（防存储型 XSS）
        new_title = re.sub(r'<[^>]*>', '', request.form.get('title', '').strip())
        if not new_title:
            flash('作业标题不能为空', 'danger')
            return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
        hw.title = new_title
        # 标题可能变化，/static/homework/<标题>/ 目录映射随之失效；
        # 同时清除附件鉴权缓存（homework:allowed_ids，TTL 120s）：
        # 旧班级（移除关联后缓存仍含本作业 id，120s 内仍可访问附件）
        # 与新班级（新增关联后缓存不含本作业 id，120s 内附件 403）
        # 都要失效——此前仅按旧班级清理，新增班级滞后最长 120s。
        class_ids = request.form.getlist('class_ids')
        from app.extensions import cache as _hw_cache
        old_class_ids = [c.id for c in hw.classes.all()]
        scope_class_ids, scope_subject_ids = _homework_teacher_scope()
        if scope_class_ids is not None:
            chosen = {parse_int(c) for c in class_ids if str(c).strip().isdigit()}
            if not chosen or not chosen.issubset(scope_class_ids):
                flash('只能给自己任课的班级发布作业', 'danger')
                return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
            sid = parse_int(request.form.get('subject_id', '').strip())
            if sid is not None and sid not in scope_subject_ids:
                flash('只能选择自己所属学科的作业', 'danger')
                return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
        for cid in set(old_class_ids) | {parse_int(c) for c in class_ids if c.strip().isdigit()}:
            _hw_cache.delete(f'homework:allowed_ids:{cid}')
        hw.description = request.form.get('description', '').strip()
        hw.subject_id = parse_int(request.form.get('subject_id', '').strip()) or None
        deadline_str = request.form.get('deadline', '').strip()
        try:
            hw.deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M') if deadline_str else None
        except ValueError:
            flash('截止日期格式不正确，请使用正确的日期格式')
            return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
        hw.is_active = request.form.get('is_active') == '1'
        # 与创建路径一致：未选班级拒绝，防止作业从全部班级静默消失。
        # 必须先于任何磁盘操作校验（此前在删附件/写新附件之后才校验，
        # 拒绝时磁盘已改而 DB 未提交：勾删的附件仍在列表里却 404）
        if not class_ids:
            flash('请至少选择一个接收班级', 'danger')
            return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))

        # 更新附件（目录按 hw.id 命名，标题变化不影响目录）。
        # 勾删的旧附件在提交成功后才删盘；中途失败回收本次新写入的文件
        hw_dir = os.path.join(HOMEWORK_DIR, str(hw.id))
        os.makedirs(hw_dir, exist_ok=True)
        existing = json.loads(hw.attachments) if hw.attachments else []
        original_names = set(existing)
        to_delete = []
        for df in request.form.getlist('delete_attachments'):
            if df in existing:
                existing.remove(df)
                to_delete.append(df)
        written = []
        for field_name in ['files', 'attachments']:
            if field_name in request.files:
                files = request.files.getlist(field_name)
                for f in files:
                    # 勾删的旧附件此刻仍在磁盘上：同名新文件允许原子替换
                    replace_ok = secure_filename_with_unicode(
                        f.filename or '').rstrip('. ') in to_delete
                    ok, msg, fname = _save_homework_attachment(
                        f, hw_dir, MAX_TEACHER_ATTACH_MB, '作业附件',
                        overwrite=replace_ok)
                    if not ok:
                        for w in written:
                            if w in original_names:
                                continue  # 已替换原有附件：记录仍指向它，不能删
                            wp = _safe_file_under(hw_dir, w)
                            if wp and os.path.isfile(wp):
                                os.remove(wp)
                        flash(msg, 'danger')
                        return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
                    if fname:
                        written.append(fname)
                        if fname not in existing:
                            existing.append(fname)
        hw.attachments = json.dumps(existing, ensure_ascii=False)

        hw.classes = []
        for cid in class_ids:
            cls = db.session.get(Class, parse_int(cid))
            if cls:
                hw.classes.append(cls)
        if scope_class_ids is not None:
            # 教师编辑页只展示其任课班级；保留作业上其他班级的关联，
            # 避免编辑自己班作业时静默剥离其他教师班级。
            for cid in old_class_ids:
                if cid in scope_class_ids:
                    continue
                cls = db.session.get(Class, cid)
                if cls and cls not in hw.classes:
                    hw.classes.append(cls)

        try:
            db.session.commit()
        except Exception:
            # 编辑提交失败：回收本次新写入且不在原记录中的文件（同名替换
            # 的旧附件仍被 DB 记录引用，保留新内容，避免误删有效附件）
            db.session.rollback()
            for name in written:
                if name in original_names:
                    continue
                fp = _safe_file_under(hw_dir, name)
                try:
                    if fp and os.path.isfile(fp):
                        os.remove(fp)
                except OSError:
                    pass
            current_app.logger.warning('编辑作业提交失败，已回收新附件', exc_info=True)
            flash('作业更新失败，请重试', 'danger')
            return redirect(url_for('homework.admin_homework_edit', hw_id=hw_id))
        for df in to_delete:
            if df in existing:
                continue  # 同一次编辑又传了同名新文件：磁盘上已是新版本
            fp = _safe_file_under(hw_dir, df)
            try:
                if fp and os.path.isfile(fp):
                    os.remove(fp)
            except OSError:
                current_app.logger.warning('删除作业附件失败（忽略）: %s', fp)
        if request.form.get('deliver_to_drive') == '1':
            # 后台线程补投递 + 前端进度条
            from app.services.delivery_worker import (
                start_homework_delivery, register_active)
            sender_name = session.get('teacher_name') or '管理员'
            start_homework_delivery(current_app._get_current_object(),
                                    hw.id, hw_dir, sender_name=sender_name)
            register_active(hw.id)
            flash('作业已更新，正在补投递附件到学生个人网盘…（可在作业列表查看进度）')
        else:
            flash('作业已更新')
        return redirect(url_for('homework.admin_homework'))

    subjects = get_subjects_cached()
    classes = get_classes_cached()
    hw_classes = [c.id for c in hw.classes.all()]
    attachments_list = json.loads(hw.attachments) if hw.attachments else []
    scope_class_ids, _ = _homework_teacher_scope()
    subjects = teacher_subjects(session.get('teacher_id')) if scope_class_ids is not None \
        else get_subjects_cached()
    classes = teacher_classes(session.get('teacher_id')) if scope_class_ids is not None \
        else get_classes_cached()
    return render_template('admin_homework_create.html',
                           hw=hw, subjects=subjects, classes=classes,
                           hw_classes=hw_classes, attachments_list=attachments_list)


@homework_bp.route('/admin/homework/<int:hw_id>/delete', methods=['POST'])
@teacher_login_required
def admin_homework_delete(hw_id):
    """删除作业"""
    hw = db.get_or_404(Homework, hw_id)
    if not _teacher_can_edit_homework(hw):
        flash('只有管理员或作业创建教师可以删除该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    # 先删除 DB 记录再删磁盘：commit 失败时磁盘文件不丢（与 resources.py
    # "先 DB 后磁盘"既定顺序一致；此前先删磁盘，commit 异常会丢文件留记录）
    hw_classes_ids = [c.id for c in hw.classes.all()]
    sub_ids = [sub.id for sub in hw.submissions]
    db.session.delete(hw)
    db.session.commit()
    # 删除附件目录与提交文件（DB 已成功删除，磁盘清理失败仅留孤儿目录）
    homework_root = os.path.realpath(HOMEWORK_DIR)
    hw_dir = os.path.realpath(os.path.join(homework_root, str(hw.id)))
    if hw_dir and hw_dir != homework_root and hw_dir.startswith(homework_root + os.sep) and os.path.isdir(hw_dir):
        shutil.rmtree(hw_dir, ignore_errors=True)
    submission_root = os.path.realpath(SUBMISSION_DIR)
    for sub_id in sub_ids:
        sub_dir = os.path.realpath(os.path.join(submission_root, str(sub_id)))
        if sub_dir != submission_root and sub_dir.startswith(submission_root + os.sep) and os.path.isdir(sub_dir):
            shutil.rmtree(sub_dir, ignore_errors=True)
    # 清除受保护静态目录鉴权缓存（按班级的作业 id 映射）
    from app.extensions import cache as _hw_cache
    for cid in hw_classes_ids:
        _hw_cache.delete(f'homework:allowed_ids:{cid}')
    flash('作业已删除')
    return redirect(url_for('homework.admin_homework'))


# ═══════════════════════════════════════════════════════════════
#  教师端：批改
# ═══════════════════════════════════════════════════════════════

@homework_bp.route('/admin/homework/<int:hw_id>/submissions')
@teacher_login_required
def admin_homework_submissions(hw_id):
    """查看作业提交列表"""
    hw = db.get_or_404(Homework, hw_id)
    if not _teacher_can_manage_homework(hw):
        flash('无权操作该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    # 筛选参数归一化：模板把这些值拼进 onchange 的 JS 字符串，实体转义
    # 在属性内 JS 上下文无效（浏览器先解码实体再解析 JS，可闭合引号注入），
    # 必须在服务端收敛为白名单值
    class_filter = str(parse_int(request.args.get('class_id', '').strip()) or '')
    _status = request.args.get('status', '').strip()
    status_filter = _status if _status in ('submitted', 'graded') else ''

    # joinedload：模板循环访问 sub.student.name / sub.student.class_.name，
    # 消除每行 2 次额外 SQL（此前缺陷：每页 20 行 ≈ 40 次 N+1 往返）
    query = HomeworkSubmission.query.options(
        joinedload(HomeworkSubmission.student).joinedload(Student.class_)
    ).filter_by(homework_id=hw_id)
    scope_class_ids = _teacher_scope_class_ids()
    if scope_class_ids is not None:
        # 管理员创建的作业可同时发给多个班；教师只应看到本人任课班级的提交。
        if not scope_class_ids:
            query = query.filter(db.false())
        else:
            query = query.join(
                Student, HomeworkSubmission.student_id == Student.id
            ).filter(Student.class_id.in_(scope_class_ids))
    cf = parse_int(class_filter)
    if cf is not None:
        if scope_class_ids is None:
            query = query.join(
                Student, HomeworkSubmission.student_id == Student.id)
        if scope_class_ids is not None and cf not in scope_class_ids:
            query = query.filter(db.false())
        else:
            query = query.filter(Student.class_id == cf)
    if status_filter:
        query = query.filter_by(status=status_filter)

    from app.utils import paginate_query
    pagination = paginate_query(
        query.order_by(HomeworkSubmission.submit_time.desc()),
        default_per_page=20, max_per_page=100
    )
    submissions = pagination.items
    classes = (get_classes_cached() if session.get('is_admin')
               else teacher_classes(session.get('teacher_id')))

    return render_template('admin_homework_submissions.html',
                           hw=hw, submissions=submissions, classes=classes,
                           class_filter=class_filter, status_filter=status_filter,
                           grade_levels=GRADE_LEVELS, pagination=pagination)


@homework_bp.route('/admin/homework/<int:hw_id>/grade/<int:sub_id>', methods=['GET', 'POST'])
@teacher_login_required
def admin_homework_grade(hw_id, sub_id):
    """批改作业"""
    hw = db.get_or_404(Homework, hw_id)
    if not _teacher_can_manage_homework(hw):
        flash('无权操作该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    # 校验提交记录属于该作业，避免 hw_id 与 sub_id 不匹配的越权操作
    sub = HomeworkSubmission.query.filter_by(id=sub_id, homework_id=hw_id).first_or_404()
    if not _teacher_can_access_submission(sub):
        flash('无权批改其他班级学生的提交', 'danger')
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))
    if request.method == 'POST':
        grade = request.form.get('grade', '').strip()
        # 校验等级必须在 GRADE_LEVELS 中，防止存入脏数据
        if grade and grade not in GRADE_LEVELS:
            flash(f'无效的等级: {grade}，请从 {", ".join(GRADE_LEVELS)} 中选择', 'danger')
            return redirect(url_for('homework.admin_homework_grade',
                                    hw_id=hw_id, sub_id=sub_id))
        sub.grade = grade
        sub.feedback = request.form.get('feedback', '').strip()
        sub.status = 'graded'
        sub.graded_at = datetime.now()
        # 记录批改者（Teacher.id）；旧版 FK 曾错误指向 student 表导致无法写入
        sub.graded_by = session.get('teacher_id') or None
        db.session.commit()
        flash(f'已批改: {sub.grade}')
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))

    sub_files = json.loads(sub.files) if sub.files else []
    return render_template('admin_homework_grade.html', hw=hw, sub=sub,
                           grade_levels=GRADE_LEVELS, sub_files=sub_files)


@homework_bp.route('/admin/homework/<int:hw_id>/submissions/<int:sub_id>/delete', methods=['POST'])
@teacher_login_required
def admin_homework_submission_delete(hw_id, sub_id):
    """删除单个提交记录"""
    hw = db.session.get(Homework, hw_id)
    if hw and not _teacher_can_manage_homework(hw):
        flash('无权操作该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    sub = HomeworkSubmission.query.filter_by(id=sub_id, homework_id=hw_id).first_or_404()
    if not _teacher_can_access_submission(sub):
        flash('无权删除其他班级学生的提交', 'danger')
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))
    # 先删 DB 记录再删磁盘（与 admin_homework_delete 的顺序约定一致）：
    # commit 失败时磁盘文件不丢，只是留下待清理的目录；反之先删磁盘，
    # commit 失败则提交记录仍在而附件全部 404，教师/学生两端都受影响
    submission_root = os.path.realpath(SUBMISSION_DIR)
    sub_dir = os.path.realpath(os.path.join(submission_root, str(sub.id)))
    db.session.delete(sub)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('删除提交记录失败，请重试', 'danger')
        current_app.logger.error('删除提交记录失败: sub_id=%s', sub_id, exc_info=True)
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))
    if sub_dir != submission_root and sub_dir.startswith(submission_root + os.sep) and os.path.isdir(sub_dir):
        shutil.rmtree(sub_dir)
    flash('提交记录已删除')
    return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))


@homework_bp.route('/admin/homework/<int:hw_id>/submissions/batch_delete', methods=['POST'])
@teacher_login_required
def admin_homework_submissions_batch_delete(hw_id):
    """批量删除提交记录"""
    hw = db.session.get(Homework, hw_id)
    if hw and not _teacher_can_manage_homework(hw):
        flash('无权操作该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    sub_ids = request.form.getlist('sub_ids')
    if not sub_ids:
        flash('未选择任何记录', 'warning')
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))
    count = 0
    submission_root = os.path.realpath(SUBMISSION_DIR)
    dirs_to_remove = []   # commit 成功后再删磁盘（防"记录在、文件失"的不一致）
    for sid in sub_ids:
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            continue
        sub = HomeworkSubmission.query.filter_by(id=sid_int, homework_id=hw_id).first()
        if sub and _teacher_can_access_submission(sub):
            sub_dir = os.path.realpath(os.path.join(submission_root, str(sub.id)))
            if sub_dir != submission_root and sub_dir.startswith(submission_root + os.sep):
                dirs_to_remove.append(sub_dir)
            db.session.delete(sub)
            count += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('批量删除失败，请重试', 'danger')
        current_app.logger.error('批量删除提交记录失败: hw_id=%s', hw_id, exc_info=True)
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))
    for sub_dir in dirs_to_remove:
        if os.path.isdir(sub_dir):
            shutil.rmtree(sub_dir)
    flash(f'已删除 {count} 条提交记录')
    return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))


@homework_bp.route('/admin/homework/<int:hw_id>/export_excellent')
@teacher_login_required
def admin_homework_export_excellent(hw_id):
    """打包下载优秀作业（A+/A等级）"""
    hw = db.get_or_404(Homework, hw_id)
    if not _teacher_can_manage_homework(hw):
        flash('无权操作该作业', 'danger')
        return redirect(url_for('homework.admin_homework'))
    excellent_query = HomeworkSubmission.query.filter(
        HomeworkSubmission.homework_id == hw_id,
        HomeworkSubmission.grade.in_(['A+', 'A'])
    )
    scope_class_ids = _teacher_scope_class_ids()
    if scope_class_ids is not None:
        if not scope_class_ids:
            excellent = []
        else:
            excellent = excellent_query.join(
                Student, HomeworkSubmission.student_id == Student.id
            ).filter(Student.class_id.in_(scope_class_ids)).all()
    else:
        excellent = excellent_query.all()

    if not excellent:
        flash('暂无优秀作业可打包', 'warning')
        return redirect(url_for('homework.admin_homework_submissions', hw_id=hw_id))

    def _build(zf):
        for sub in excellent:
            student = sub.student
            # 姓名/学号可能含 /、\、.. 等路径分隔符，直接拼入 zip 条目路径
            # 会在解压时越级写入（zip-slip），须清洗后再作为目录名
            safe_name = secure_filename_with_unicode(student.name) if student else '未知学生'
            safe_number = secure_filename_with_unicode(student.student_number) if student else ''
            prefix = f'{sub.grade}_{safe_name}_{safe_number}'
            # 文本内容
            if sub.text_content:
                zf.writestr(f'{prefix}/作业内容.txt', sub.text_content)
            # 上传文件
            if sub.files:
                files_list = json.loads(sub.files)
                sub_dir = os.path.join(SUBMISSION_DIR, str(sub.id))
                for fn in files_list:
                    # 文件名同样须位于提交目录内，防数据库被篡改后路径逃逸
                    fp = _safe_file_under(sub_dir, fn)
                    if fp and os.path.exists(fp):
                        zf.write(fp, f'{prefix}/{secure_filename_with_unicode(fn)}')
    return send_temp_zip(_build, f'优秀作业_{hw.title}.zip')


# ═══════════════════════════════════════════════════════════════
#  学生端
# ═══════════════════════════════════════════════════════════════

@homework_bp.route('/student/homework')
@login_required
def student_homework():
    """学生作业列表"""
    student_id = session.get('student_id')
    student = db.session.get(Student, student_id)
    if not student or not student.class_id:
        flash('未分配班级')
        return redirect(url_for('resources.study'))

    # 获取该生班级的全部作业；is_active 只控制是否还能提交，不控制历史查看
    from app.utils import paginate_query
    pagination = paginate_query(
        Homework.query.options(joinedload(Homework.subject)).filter(
            Homework.classes.any(id=student.class_id)
        ).order_by(Homework.create_time.desc()),
        default_per_page=20, max_per_page=100
    )
    my_homeworks = pagination.items

    # 批量加载提交状态，消除 N+1
    submissions = {}
    if my_homeworks:
        hw_ids = [hw.id for hw in my_homeworks]
        for sub in HomeworkSubmission.query.filter(
                HomeworkSubmission.homework_id.in_(hw_ids),
                HomeworkSubmission.student_id == student_id).all():
            submissions[sub.homework_id] = sub

    return render_template('student_homework.html', homeworks=my_homeworks,
                           submissions=submissions, grade_levels=GRADE_LEVELS,
                           pagination=pagination)


@homework_bp.route('/student/homework/<int:hw_id>', methods=['GET', 'POST'])
@login_required
def student_homework_submit(hw_id):
    """学生提交作业"""
    _ensure_dirs()
    hw = db.get_or_404(Homework, hw_id)
    student_id = session.get('student_id')
    if not _student_can_access_homework(hw, student_id):
        flash('无权访问该作业')
        return redirect(url_for('homework.student_homework'))
    existing = HomeworkSubmission.query.filter_by(
        homework_id=hw_id, student_id=student_id).first()

    if request.method == 'POST':
        if not hw.is_active:
            flash('作业已关闭，无法提交', 'warning')
            return redirect(url_for('homework.student_homework'))
        # 重交加行锁防并发覆盖（PostgreSQL SELECT ... FOR UPDATE）：
        # 重交是「读 existing.files → 合并新附件 → 写回」三段式，双标签页/
        # 弱网重试并发提交时，后完成者会用旧快照覆盖先提交者的附件列表，
        # 且孤儿清理会把先提交者的附件物理删除。加锁后两个并发提交串行化，
        # 后者读到前者提交后的最新 files 再合并（SQLite 不支持行锁但整库
        # 写串行，天然无此竞态；首次提交无行可锁，由唯一约束兜底）。
        existing = HomeworkSubmission.query.filter_by(
            homework_id=hw_id, student_id=student_id
        ).with_for_update().first()

        # 截止时间服务端强制校验：前端计时不可信，过期后一律拒绝提交/重交，
        # 防止逾期提交，以及"逾期重交把已批改的 grade/feedback 清空"。
        if hw.deadline and datetime.now() > hw.deadline:
            flash('作业已截止，无法提交')
            return redirect(url_for('homework.student_homework'))
        text_content = request.form.get('text_content', '').strip()
        # 保存上传文件（使用 uuid 避免并发冲突；危险扩展名/超大小拒绝）
        sub_dir = os.path.join(SUBMISSION_DIR,
                               str(existing.id) if existing else 'tmp_' + str(uuid.uuid4().hex[:8]))
        uploaded_files = []
        old_record_files = set()
        if existing and existing.files:
            try:
                old_record_files = {f for f in json.loads(existing.files) if isinstance(f, str)}
            except (TypeError, ValueError):
                old_record_files = set()
        new_upload_bytes = 0
        for field_name in ['files', 'attachments']:
            if field_name in request.files:
                files = request.files.getlist(field_name)
                for f in files:
                    ok, msg, fname = _save_homework_attachment(
                        f, sub_dir, MAX_STUDENT_ATTACH_MB, '作业附件',
                        overwrite=bool(existing))
                    if not ok:
                        # 清理本次已写入的附件：首次提交删整个 tmp_ 目录；
                        # 重交只删本次新写入、且不在原记录中的文件（原记录里的
                        # 旧附件绝不误删），否则它们既不入库又挡住下次同名重传
                        _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files)
                        flash(msg, 'danger')
                        return redirect(url_for('homework.student_homework'))
                    if fname:
                        uploaded_files.append(fname)
                        try:
                            new_upload_bytes += os.path.getsize(os.path.join(sub_dir, fname))
                        except OSError:
                            pass
                        if new_upload_bytes > MAX_STUDENT_SUBMIT_MB * 1024 * 1024:
                            _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files)
                            flash(f'本次上传附件合计超过 {MAX_STUDENT_SUBMIT_MB}MB，请分次提交或压缩后重试', 'danger')
                            return redirect(url_for('homework.student_homework'))

        # 提交聚合上限（防反复重交无限追加旧附件占满磁盘）：
        # 目录实际占用包含历史附件，未去重同名覆盖的旧文件（保守高估）
        final_names = old_record_files | set(uploaded_files)
        if uploaded_files and len(final_names) > MAX_SUBMISSION_FILES:
            _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files)
            flash(f'单份作业最多保留 {MAX_SUBMISSION_FILES} 个附件，请删除旧附件后重试', 'danger')
            return redirect(url_for('homework.student_homework'))
        if uploaded_files and _dir_size_bytes(sub_dir) > MAX_SUBMISSION_TOTAL_MB * 1024 * 1024:
            _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files)
            flash(f'单份作业附件累计超过 {MAX_SUBMISSION_TOTAL_MB}MB，请压缩或删除旧附件后重试', 'danger')
            return redirect(url_for('homework.student_homework'))

        # 空提交拒绝：无文本、无新文件、且重交时原记录也无文件
        has_existing_files = bool(existing and existing.files and existing.files != '[]')
        if not text_content and not uploaded_files and not has_existing_files:
            # 同路径清理：临时目录内可能已写入此前循环保存的文件
            if os.path.basename(sub_dir).startswith('tmp_'):
                shutil.rmtree(sub_dir, ignore_errors=True)
            flash('请填写说明或上传附件', 'warning')
            return redirect(url_for('homework.student_homework'))

        if existing:
            # 重交（text_content 允许清空，覆盖旧文本）
            existing.text_content = text_content
            if uploaded_files:
                # 重交为"追加"而非"整体替换"：学生部分重传时必须保留未重传的
                # 旧附件（此前缺陷：已交 3 个附件、重交只补传 1 个 → 旧附件
                # 全部被删且不可恢复，教师批改时附件缺失）。
                # 保序去重（dict.fromkeys）：同名文件重传时不产生重复条目。
                old_files = []
                if existing.files:
                    try:
                        old_files = json.loads(existing.files)
                    except (TypeError, ValueError):
                        old_files = []
                merged_files = list(dict.fromkeys(
                    [f for f in old_files if isinstance(f, str)] + uploaded_files))
                existing.files = json.dumps(merged_files, ensure_ascii=False)
                # 仅清理"不在合并记录中"的磁盘孤儿（历史遗留），不再误删有效旧附件
                try:
                    import shutil as _shutil
                    if os.path.isdir(sub_dir):
                        for old_name in os.listdir(sub_dir):
                            if old_name in merged_files:
                                continue
                            old_path = os.path.join(sub_dir, old_name)
                            if os.path.isdir(old_path):
                                _shutil.rmtree(old_path, ignore_errors=True)
                            else:
                                os.remove(old_path)
                except OSError:
                    current_app.logger.warning('重交清理孤儿附件失败', exc_info=True)
            existing.resubmit_time = datetime.now()
            existing.status = 'submitted'
            # 等级作废需重新批改；保留教师评语文本作为复核参考（避免劳动全部丢失）
            existing.grade = None
            flash('作业已重新提交')
        else:
            # 首次提交
            sub = HomeworkSubmission(
                homework_id=hw_id, student_id=student_id,
                text_content=text_content,
                files=json.dumps(uploaded_files, ensure_ascii=False))
            db.session.add(sub)
            try:
                # 用 flush 获取 id 后重命名临时目录
                if uploaded_files:
                    db.session.flush()
                    new_dir = os.path.join(SUBMISSION_DIR, str(sub.id))
                    if os.path.exists(sub_dir):
                        try:
                            os.rename(sub_dir, new_dir)
                        except OSError:
                            # rename 失败（目标已存在/跨设备等）：回滚提交记录并清理
                            # 临时目录，提示学生重新提交。此前缺陷：未 rollback 仍
                            # commit → 提交记录引用已被删除的 tmp 目录，附件全部 404
                            db.session.rollback()
                            shutil.rmtree(sub_dir, ignore_errors=True)
                            current_app.logger.warning('作业提交目录 rename 失败，已回滚并清理临时目录', exc_info=True)
                            flash('作业提交失败（文件目录异常），请重新提交', 'danger')
                            return redirect(url_for('homework.student_homework'))
            except IntegrityError:
                # 并发/双击重复提交：flush 阶段唯一约束冲突。此前 flush 在 try 外
                # → 异常未捕获直接 500；且 tmp_ 目录在 flush 抛错与 commit 回滚
                # 两条路径下均残留磁盘。
                db.session.rollback()
                if os.path.basename(sub_dir).startswith('tmp_') and os.path.isdir(sub_dir):
                    shutil.rmtree(sub_dir, ignore_errors=True)
                flash('检测到重复提交，已保留原记录。请确认你的附件已包含最新文件（本次上传的临时文件已清理，未合并进原记录）')
                return redirect(url_for('homework.student_homework'))
            flash('作业已提交')

        try:
            db.session.commit()
        except IntegrityError:
            # 并发/双击重复提交：唯一约束冲突（commit 阶段），回滚后按"已提交"处理。
            # 首次提交路径的 tmp_ 目录此时已成孤儿，一并清理（重交路径 sub_dir
            # 是现有附件目录，以 tmp_ 前缀判别，绝不误删）
            db.session.rollback()
            if os.path.basename(sub_dir).startswith('tmp_') and os.path.isdir(sub_dir):
                shutil.rmtree(sub_dir, ignore_errors=True)
            flash('检测到重复提交，已保留原记录。请确认你的附件已包含最新文件（本次上传的临时文件已清理，未合并进原记录）')
            return redirect(url_for('homework.student_homework'))
        except Exception as e:
            db.session.rollback()
            # 非唯一约束的提交失败（连接中断/磁盘等）：回收本次新写入的
            # 附件——首交目录已 rename 为 submissions/<id>，重交则删本次
            # 新文件（旧附件不误删）。
            if existing:
                _cleanup_new_uploads(sub_dir, uploaded_files, old_record_files)
            else:
                new_dir = os.path.join(SUBMISSION_DIR,
                                       str(getattr(sub, 'id', 0) or 0))
                if os.path.isdir(new_dir):
                    shutil.rmtree(new_dir, ignore_errors=True)
                elif os.path.basename(sub_dir).startswith('tmp_') and os.path.isdir(sub_dir):
                    shutil.rmtree(sub_dir, ignore_errors=True)
            current_app.logger.error(f"作业提交失败: {str(e)}", exc_info=True)
            flash('作业提交失败，请重试')
        return redirect(url_for('homework.student_homework'))

    attachments = json.loads(hw.attachments) if hw.attachments else []
    existing_files = []
    if existing and existing.files:
        try:
            existing_files = [f for f in json.loads(existing.files)
                              if isinstance(f, str)]
        except (TypeError, ValueError):
            existing_files = []
    return render_template('student_homework_submit.html',
                           hw=hw, existing=existing, attachments=attachments,
                           existing_files=existing_files)


@homework_bp.route('/student/homework/<int:hw_id>/result')
@login_required
def student_homework_result(hw_id):
    """学生查看批改结果"""
    hw = db.get_or_404(Homework, hw_id)
    student_id = session.get('student_id')
    # 作业停用仅停止收集，不阻止学生查看已批改历史；移除班级归属仍禁止访问。
    if not _student_can_access_homework(hw, student_id):
        flash('无权访问该作业')
        return redirect(url_for('homework.student_homework'))
    sub = HomeworkSubmission.query.filter_by(
        homework_id=hw_id, student_id=student_id).first_or_404()
    sub_files = json.loads(sub.files) if sub.files else []
    return render_template('student_homework_result.html', hw=hw, sub=sub,
                           grade_levels=GRADE_LEVELS, sub_files=sub_files)


@homework_bp.route('/admin/homework/preview-submission/<int:sub_id>/<path:filename>')
@teacher_login_required
def preview_submission_file(sub_id, filename):
    """教师端预览学生提交的文件 — 浏览器优先打开，不强制下载"""
    sub = db.get_or_404(HomeworkSubmission, sub_id)
    # 文件预览同样受作业归属校验，防止教师越权查看他人作业的提交文件
    hw = db.session.get(Homework, sub.homework_id)
    if hw and not _teacher_can_manage_homework(hw):
        return '无权访问', 403
    if not _teacher_can_access_submission(sub):
        return '无权访问', 403
    safe_filename = (filename or '').replace('\\', '/').lstrip('/')
    if '..' in safe_filename.split('/'):
        return '非法文件路径', 400
    base_dir = os.path.realpath(os.path.join(SUBMISSION_DIR, str(sub.id)))
    fp = os.path.realpath(os.path.normpath(os.path.join(base_dir, safe_filename)))
    if fp != base_dir and not fp.startswith(base_dir + os.sep):
        return '非法文件路径', 400
    if not os.path.exists(fp):
        return '文件不存在', 404
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    # Office 文档 → inline，浏览器尝试打开或提示安装插件
    office_exts = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
    office_mimes = {
        'doc': 'application/msword', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xls': 'application/vnd.ms-excel', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ppt': 'application/vnd.ms-powerpoint', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }
    # conditional=True：磁盘直送附件支持 Range/304（断点续传、预览 seek）
    if ext in office_exts:
        return send_file(fp, conditional=True,
                         mimetype=office_mimes.get(ext, 'application/octet-stream'),
                         as_attachment=False, download_name=safe_filename)
    # 其他文件：浏览器可预览则 inline，否则下载
    inline_exts = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'txt', 'html', 'htm', 'md',
                   'py', 'js', 'css', 'json', 'xml', 'csv', 'mp3', 'wav', 'ogg', 'mp4', 'webm'}
    if ext in inline_exts:
        return send_file(fp, conditional=True, as_attachment=False,
                         mimetype=safe_inline_mimetype(safe_filename))
    return send_large_download(fp, conditional=True, as_attachment=True)


@homework_bp.route('/student/homework/preview/<int:hw_id>/<path:filename>')
@login_required
def preview_attachment(hw_id, filename):
    """预览作业附件 — 使用 JitViewer 统一预览"""
    hw = db.get_or_404(Homework, hw_id)
    student_id = session.get('student_id')
    if not _student_can_access_homework(hw, student_id):
        return '无权访问', 403
    safe_filename = (filename or '').replace('\\', '/').lstrip('/')
    if '..' in safe_filename.split('/'):
        return '非法文件路径', 400
    hw_dir = os.path.realpath(os.path.join(HOMEWORK_DIR, str(hw.id)))
    fp = os.path.realpath(os.path.normpath(os.path.join(hw_dir, safe_filename)))
    if fp != hw_dir and not fp.startswith(hw_dir + os.sep):
        return '非法文件路径', 400
    if not os.path.exists(fp):
        return '文件不存在', 404
    ext = safe_filename.rsplit('.', 1)[-1].lower() if '.' in safe_filename else ''

    file_url = url_for(
        'static',
        filename=f'homework/{hw.id}/{safe_filename}'
    )
    download_url = file_url

    # 判断媒体类型用于回退
    media_type_map = {
        'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
        'bmp': 'image', 'webp': 'image',
        'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio',
        'mp4': 'video', 'webm': 'video',
        'txt': 'text', 'html': 'text', 'htm': 'text',
    }
    media_type = media_type_map.get(ext, '')

    return render_template('document_preview.html',
                           filename=safe_filename,
                           file_url=file_url,
                           download_url=download_url,
                           media_type=media_type,
                           back_url=url_for('homework.student_homework'))


@homework_bp.route('/student/homework/<int:hw_id>/submission/<int:sub_id>/files/delete',
                    methods=['POST'])
@login_required
def student_delete_submission_file(hw_id, sub_id):
    """学生删除本人本次作业的一个旧附件（重交前清理容量/数量）。"""
    student_id = session.get('student_id')
    hw = db.get_or_404(Homework, hw_id)
    if not _student_can_access_homework(hw, student_id):
        return '无权访问', 403
    if not hw.is_active:
        flash('作业已关闭，不能修改提交附件', 'warning')
        return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))
    if hw.deadline and datetime.now() > hw.deadline:
        flash('作业已截止，不能修改提交附件', 'warning')
        return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))
    sub = HomeworkSubmission.query.filter_by(
        id=sub_id, homework_id=hw_id, student_id=student_id
    ).with_for_update().first_or_404()
    filename = (request.form.get('filename') or '').strip()
    try:
        files = [f for f in json.loads(sub.files or '[]') if isinstance(f, str)]
    except (TypeError, ValueError):
        files = []
    if not filename or filename not in files:
        flash('附件不存在或不属于本次提交', 'danger')
        return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))
    remaining = [f for f in files if f != filename]
    if not remaining and not (sub.text_content or '').strip():
        flash('至少保留文字作答或一个附件', 'warning')
        return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))
    sub.files = json.dumps(remaining, ensure_ascii=False)
    if sub.status == 'graded':
        # 删除已批改作品的附件视为重新提交，需要教师重新批改。
        sub.grade = None
        sub.status = 'submitted'
        sub.resubmit_time = datetime.now()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('删除附件失败，请重试', 'danger')
        current_app.logger.error('学生删除作业附件失败: sub_id=%s', sub_id,
                                 exc_info=True)
        return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))
    fp = _safe_file_under(os.path.join(SUBMISSION_DIR, str(sub.id)), filename)
    if fp:
        try:
            if os.path.isfile(fp):
                os.remove(fp)
        except OSError:
            current_app.logger.warning('删除作业附件失败（已从记录移除）: %s', fp)
    flash('附件已删除', 'success')
    return redirect(url_for('homework.student_homework_submit', hw_id=hw_id))


@homework_bp.route('/student/homework/preview-submission/<int:sub_id>/<path:filename>')
@login_required
def student_preview_submission(sub_id, filename):
    """学生预览本人提交的作业附件 — 复用 JitViewer 文档预览。

    仅当前学生本人的提交可读；文件位于 submissions/<sub_id>/，与静态鉴权
    （/static/submissions/<sub_id>/...）保持同一所有权口径。
    """
    student_id = session.get('student_id')
    sub = db.get_or_404(HomeworkSubmission, sub_id)
    if sub.student_id != student_id:
        return '无权访问', 403
    hw = db.session.get(Homework, sub.homework_id)
    if not hw or not _student_can_access_homework(hw, student_id):
        return '无权访问', 403
    safe_filename = (filename or '').replace('\\', '/').lstrip('/')
    if not safe_filename or '..' in safe_filename.split('/'):
        return '非法文件路径', 400
    base_dir = os.path.realpath(os.path.join(SUBMISSION_DIR, str(sub.id)))
    fp = os.path.realpath(os.path.normpath(os.path.join(base_dir, safe_filename)))
    if fp != base_dir and not fp.startswith(base_dir + os.sep):
        return '非法文件路径', 400
    if not os.path.isfile(fp):
        return '文件不存在', 404
    ext = safe_filename.rsplit('.', 1)[-1].lower() if '.' in safe_filename else ''
    file_url = url_for('static', filename=f'submissions/{sub.id}/{safe_filename}')
    media_type_map = {
        'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
        'bmp': 'image', 'webp': 'image', 'mp3': 'audio', 'wav': 'audio',
        'ogg': 'audio', 'mp4': 'video', 'webm': 'video', 'txt': 'text',
        'html': 'text', 'htm': 'text', 'md': 'text', 'csv': 'text',
    }
    return render_template('document_preview.html',
                           filename=safe_filename,
                           file_url=file_url,
                           download_url=file_url,
                           media_type=media_type_map.get(ext, ''),
                           back_url=url_for('homework.student_homework_result',
                                            hw_id=hw.id))



# ═══════════════════════════════════════════════════════════════
#  统计与导出
# ═══════════════════════════════════════════════════════════════

@homework_bp.route('/admin/statistics')
@teacher_login_required
def admin_statistics():
    """综合统计仪表板（教师仅统计本人任课班级）"""
    from app.models import Result, Exam
    scope_class_ids, _ = _homework_teacher_scope()
    is_admin_view = scope_class_ids is None
    if is_admin_view:
        classes = get_classes_cached()
        subjects = get_subjects_cached()
    else:
        classes = Class.query.filter(Class.id.in_(scope_class_ids)).order_by(
            Class.name).all() if scope_class_ids else []
        subjects = teacher_subjects(session.get('teacher_id'))

    # 作业统计（教师仅统计覆盖本人班级的作业）
    hw_query = Homework.query
    sub_query = HomeworkSubmission.query
    result_query_total = Result.query
    if scope_class_ids is not None:
        class_hw_ids = db.session.query(homework_classes.c.homework_id).filter(
            homework_classes.c.class_id.in_(scope_class_ids))
        hw_query = hw_query.filter(Homework.id.in_(class_hw_ids))
        sub_query = sub_query.join(
            Student, Student.id == HomeworkSubmission.student_id).filter(
            Student.class_id.in_(scope_class_ids))
        result_query_total = result_query_total.join(
            Student, Student.id == Result.student_id).filter(
            Student.class_id.in_(scope_class_ids))
    hw_total = hw_query.count()
    hw_active = hw_query.filter(Homework.is_active.is_(True)).count()
    subs_total = sub_query.count()
    subs_ungraded = sub_query.filter(HomeworkSubmission.status == 'submitted').count()

    # 考试统计（教师仅统计本人班级学生的成绩）
    if is_admin_view:
        exams = Exam.query.order_by(Exam.create_time.desc()).all()
        exams_total = Exam.query.filter_by(is_active=True).count()
    else:
        exam_id_rows = db.session.query(Result.exam_id).join(
            Student, Student.id == Result.student_id).filter(
            Student.class_id.in_(scope_class_ids)).distinct()
        exams = Exam.query.filter(Exam.id.in_(exam_id_rows)).order_by(
            Exam.create_time.desc()).all()
        exams_total = Exam.query.filter(
            Exam.id.in_(exam_id_rows), Exam.is_active.is_(True)).count()
    results_total = result_query_total.count()

    # 班级作业提交率（批量查询，消除 N+1）
    from sqlalchemy import func as sa_func
    class_hw_stats = []

    # 批量获取各班学生数
    student_counts = dict(
        db.session.query(Student.class_id, sa_func.count(Student.id))
        .filter(Student.class_id.in_([c.id for c in classes]))
        .group_by(Student.class_id).all()
    ) if classes else {}

    # 批量获取各班活跃作业数
    hw_counts = {}
    if classes:
        # bindparam(expanding=True) 展开 IN 参数列表：
        # 传 tuple 在 SQLAlchemy 2.x 下会被当作单个值绑定，导致查询结果错误或报错
        from sqlalchemy import bindparam, text as sa_text
        rows = db.session.execute(
            sa_text(
                "SELECT hc.class_id, COUNT(DISTINCT h.id) FROM homework h"
                " JOIN homework_classes hc ON hc.homework_id = h.id"
                " WHERE h.is_active = TRUE AND hc.class_id IN :cids"
                " GROUP BY hc.class_id"
            ).bindparams(bindparam('cids', expanding=True)),
            {'cids': [c.id for c in classes]}
        ).fetchall()
        hw_counts = {row[0]: row[1] for row in rows}

    # 批量获取各班提交数（仅活跃作业；此前统计全部提交 → 作业停用后
    # 分子保留分母减少，提交率可超过 100%）
    sub_counts = dict(
        db.session.query(Student.class_id, sa_func.count(HomeworkSubmission.id))
        .join(HomeworkSubmission, HomeworkSubmission.student_id == Student.id)
        .join(Homework, HomeworkSubmission.homework_id == Homework.id)
        .filter(Student.class_id.in_([c.id for c in classes]),
                Homework.is_active.is_(True))
        .group_by(Student.class_id).all()
    ) if classes else {}

    for c in classes:
        student_count = student_counts.get(c.id, 0)
        if student_count > 0:
            hw_for_class = hw_counts.get(c.id, 0)
            subs_count = sub_counts.get(c.id, 0)
            rate = round(subs_count / max(student_count * max(hw_for_class, 1), 1) * 100, 1)
            class_hw_stats.append({
                'class': c, 'student_count': student_count,
                'hw_count': hw_for_class, 'subs_count': subs_count, 'rate': rate
            })

    # 考试成绩记录（支持筛选 + 分页渲染）
    from app.utils import paginate_query
    # 筛选参数归一化为纯数字字符串：模板把这些值拼进 onchange 的 JS
    # 字符串，实体转义在属性内 JS 上下文无效（可闭合引号注入代码）
    ef = parse_int(request.args.get('exam_id', '').strip())
    cf = parse_int(request.args.get('class_id', '').strip())
    exam_filter = str(ef) if ef is not None else ''
    class_filter = str(cf) if cf is not None else ''
    results_query = Result.query
    if scope_class_ids is not None:
        results_query = results_query.join(
            Student, Result.student_id == Student.id).filter(
            Student.class_id.in_(scope_class_ids))
    if ef is not None:
        results_query = results_query.filter_by(exam_id=ef)
    if cf is not None:
        results_query = results_query.filter(
            Student.class_id == cf)
    results_pagination = paginate_query(
        results_query.order_by(Result.submit_time.desc()),
        default_per_page=20, max_per_page=100
    )
    results = results_pagination.items

    # 预加载学生和班级信息
    # joinedload(class_)：模板每行访问 student.class_.name，消除 N+1
    student_ids = {r.student_id for r in results}
    students_map = {}
    if student_ids:
        for s in Student.query.options(joinedload(Student.class_)).filter(
                Student.id.in_(student_ids)).all():
            students_map[s.id] = s

    # 构建考试名称映射
    exam_names = {e.id: e.name for e in exams}  # 复用上方已加载的全量列表，省一次全表扫描

    return render_template('admin_statistics.html', classes=classes,
                           subjects=subjects, class_hw_stats=class_hw_stats,
                           hw_total=hw_total, hw_active=hw_active,
                           subs_total=subs_total, subs_ungraded=subs_ungraded,
                           exams_total=exams_total, results_total=results_total,
                           exams=exams, results=results, exam_names=exam_names,
                           students_map=students_map,
                           exam_filter=exam_filter, class_filter=class_filter,
                           results_pagination=results_pagination)


@homework_bp.route('/admin/statistics/results/<int:result_id>/delete', methods=['POST'])
@admin_login_required
def admin_delete_result(result_id):
    """删除单条考试成绩"""
    from app.models import Result
    from app.services.scoring_service import delete_exam_result
    r = db.get_or_404(Result, result_id)
    try:
        info = delete_exam_result(r)
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后执行
        from app.services.scoring_service import finalize_exam_result_deletion
        finalize_exam_result_deletion(info)
        flash(f"已删除学生 {info['student_name']} 的成绩记录")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除成绩失败: {e}", exc_info=True)
        flash('删除成绩失败', 'danger')
    return redirect(url_for('homework.admin_statistics'))


@homework_bp.route('/admin/statistics/results/batch_delete', methods=['POST'])
@admin_login_required
def admin_batch_delete_results():
    """批量删除考试成绩"""
    from app.models import Result
    from app.services.scoring_service import delete_exam_result
    result_ids = request.form.getlist('result_ids')
    if not result_ids:
        flash('未选择任何记录', 'warning')
        return redirect(url_for('homework.admin_statistics'))
    count = 0
    deleted_infos = []
    for rid in result_ids:
        rid_int = parse_int(rid)
        if rid_int is None:
            continue
        r = db.session.get(Result, rid_int)
        if r:
            deleted_infos.append(
                delete_exam_result(r, log_action='批量删除学生成绩'))
            count += 1
    try:
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后统一执行
        if deleted_infos:
            from app.services.scoring_service import finalize_exam_result_deletion
            finalize_exam_result_deletion(*deleted_infos)
        flash(f'已删除 {count} 条成绩记录')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量删除成绩失败: {e}", exc_info=True)
        flash('批量删除成绩失败', 'danger')
    return redirect(url_for('homework.admin_statistics'))


@homework_bp.route('/admin/statistics/export')
@admin_login_required
def admin_export_statistics():
    """导出综合统计为 Excel"""
    try:
        import openpyxl
    except ImportError:
        flash('请安装 openpyxl: pip install openpyxl', 'danger')
        return redirect(url_for('homework.admin_statistics'))

    wb = openpyxl.Workbook()

    # Sheet 1: 班级作业统计
    ws1 = wb.active
    ws1.title = '班级作业统计'
    ws1.append(['班级', '学生数', '作业数', '提交数', '提交率(%)'])
    classes = get_classes_cached()
    class_ids = [c.id for c in classes]
    # 批量聚合替代每班 3 次 count（此前 N+1：班级数 × 3 次查询）
    stu_counts = {}
    if class_ids:
        for cid, cnt in db.session.query(
                Student.class_id, _func.count(Student.id)
        ).filter(Student.class_id.in_(class_ids)).group_by(Student.class_id).all():
            stu_counts[cid] = cnt
    # 活跃作业数（homework_classes 关联一次统计）
    hw_counts = {}
    if class_ids:
        rel_rows = db.session.execute(
            homework_classes.select().where(
                homework_classes.c.class_id.in_(class_ids))
        ).all()
        if rel_rows:
            rel_hw_ids = [r[0] for r in rel_rows]
            active_ids = {hid for (hid,) in db.session.query(Homework.id).filter(
                Homework.id.in_(rel_hw_ids), Homework.is_active.is_(True)).all()}
            for hw_id, cls_id in rel_rows:
                if hw_id in active_ids:
                    hw_counts[cls_id] = hw_counts.get(cls_id, 0) + 1
    # 提交数（活跃作业口径与仪表板一致）：join 一次按班级聚合
    sub_counts = {}
    if class_ids:
        for cid, cnt in db.session.query(
                Student.class_id, _func.count(HomeworkSubmission.id)
        ).join(Student, HomeworkSubmission.student_id == Student.id).join(
            Homework, HomeworkSubmission.homework_id == Homework.id
        ).filter(Student.class_id.in_(class_ids),
                 Homework.is_active.is_(True)).group_by(Student.class_id).all():
            sub_counts[cid] = cnt
    for c in classes:
        sc = stu_counts.get(c.id, 0)
        hc = hw_counts.get(c.id, 0)
        subc = sub_counts.get(c.id, 0)
        rate = round(subc / max(sc * max(hc, 1), 1) * 100, 1)
        ws1.append([c.name, sc, hc, subc, rate])

    # Sheet 2: 作业等级分布（批量加载提交与班级关系，消除逐作业查询的 N+1）
    ws2 = wb.create_sheet('作业等级分布')
    ws2.append(['作业标题', '班级', '总提交'] + GRADE_LEVELS + ['未批改'])
    all_hw = Homework.query.order_by(Homework.create_time.desc()).all()
    hw_ids = [hw.id for hw in all_hw]
    # 提交按 homework_id 分组（列裁剪：仅统计所需 grade/status，
    # 此前全列加载会把 text_content/files 大 TEXT 列一并取出）
    subs_by_hw = {}
    if hw_ids:
        for row in db.session.query(
                HomeworkSubmission.homework_id, HomeworkSubmission.grade,
                HomeworkSubmission.status
        ).filter(HomeworkSubmission.homework_id.in_(hw_ids)).all():
            subs_by_hw.setdefault(row.homework_id, []).append(row)
    # 作业-班级名映射（一次关联表查询）
    hw_class_map = {}
    if hw_ids:
        rel_rows = db.session.execute(
            homework_classes.select().where(
                homework_classes.c.homework_id.in_(hw_ids))
        ).all()
        if rel_rows:
            cls_ids = {r[1] for r in rel_rows}
            cls_map = {c.id: c.name for c in
                       Class.query.filter(Class.id.in_(cls_ids)).all()}
            for hw_id, cls_id in rel_rows:
                hw_class_map.setdefault(hw_id, []).append(cls_map.get(cls_id, ''))
    for hw in all_hw:
        subs = subs_by_hw.get(hw.id, [])
        total = len(subs)
        grade_counts = {g: sum(1 for s in subs if s.grade == g) for g in GRADE_LEVELS}
        ungraded = sum(1 for s in subs if s.status == 'submitted')
        ws2.append([hw.title, ', '.join(hw_class_map.get(hw.id, [])), total] +
                   [grade_counts[g] for g in GRADE_LEVELS] + [ungraded])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f'综合统计_{datetime.now().strftime("%Y%m%d")}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _scan_python_orphans():
    """扫描 Python 孤儿文件，返回 (文件数, 字节数)。

    判定：python_answers/python_files 目录中文件名不在 DB file_path 引用的
    即孤儿（删除题目/学生后残留）；另含历史遗留目录 uploads/python
    （旧版本存储路径，DB 零引用）。只统计不删除。
    """
    from app.models import PythonAnswer, PythonFile
    uploads = os.path.join(_BASE, 'static', 'uploads')
    valid = set()
    for row in db.session.query(PythonAnswer.file_path).all():
        if row[0]:
            valid.add(os.path.normpath(row[0]))
    for row in db.session.query(PythonFile.file_path).all():
        if row[0]:
            valid.add(os.path.normpath(row[0]))
    count = 0
    size = 0
    for sub in ('python_answers', 'python_files'):
        sub_dir = os.path.join(uploads, sub)
        if not os.path.isdir(sub_dir):
            continue
        for fn in os.listdir(sub_dir):
            if os.path.normpath(f'{sub}/{fn}') in valid:
                continue
            fp = os.path.join(sub_dir, fn)
            if os.path.isfile(fp):
                count += 1
                try:
                    size += os.path.getsize(fp)
                except OSError:
                    pass
    # 历史遗留目录 uploads/python（旧版本路径，DB 零引用）整体计为孤儿
    legacy = os.path.join(uploads, 'python')
    if os.path.isdir(legacy):
        for root, _, files in os.walk(legacy):
            for f in files:
                fp = os.path.join(root, f)
                count += 1
                try:
                    size += os.path.getsize(fp)
                except OSError:
                    pass
    return count, size


@homework_bp.route('/admin/backup/cleanup-python-orphans', methods=['POST'])
@admin_login_required
def cleanup_python_orphans():
    """清理 Python 孤儿文件（DB 已无引用的残留 + 历史遗留目录）。"""
    from app.models import PythonAnswer, PythonFile
    uploads = os.path.join(_BASE, 'static', 'uploads')
    valid = set()
    for row in db.session.query(PythonAnswer.file_path).all():
        if row[0]:
            valid.add(os.path.normpath(row[0]))
    for row in db.session.query(PythonFile.file_path).all():
        if row[0]:
            valid.add(os.path.normpath(row[0]))
    removed = 0
    freed = 0
    for sub in ('python_answers', 'python_files'):
        sub_dir = os.path.join(uploads, sub)
        if not os.path.isdir(sub_dir):
            continue
        for fn in os.listdir(sub_dir):
            if os.path.normpath(f'{sub}/{fn}') in valid:
                continue
            fp = os.path.join(sub_dir, fn)
            if os.path.isfile(fp):
                try:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
                    removed += 1
                except OSError:
                    pass
    # 历史遗留目录 uploads/python 整体清理（DB 零引用确认后）
    legacy = os.path.join(uploads, 'python')
    if os.path.isdir(legacy):
        try:
            for root, _, files in os.walk(legacy):
                for f in files:
                    try:
                        freed += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            shutil.rmtree(legacy, ignore_errors=True)
        except OSError:
            pass
    current_app.logger.info(
        f'清理 Python 孤儿文件: {removed} 个, {freed // (1024 * 1024)}MB')
    flash(f'已清理 {removed} 个孤儿文件，释放约 {freed // (1024 * 1024)}MB', 'success')
    return redirect(url_for('homework.admin_backup'))


@homework_bp.route('/admin/backup')
@admin_login_required
def admin_backup():
    """数据库备份页面"""
    # 使用 PostgreSQL 统计查询获取数据库大小
    try:
        result = db.session.execute(text(
            "SELECT pg_database_size(current_database())"
        )).scalar()
        db_size = result or 0
    except Exception:
        db_size = 0
    uploads_dir = os.path.join(_BASE, 'static', 'uploads')
    uploads_size = 0
    uploads_count = 0
    from app.extensions import cache as _bk_cache
    if os.path.isdir(uploads_dir):
        # 全量 os.walk + getsize 统计（GB 级目录每次打开备份页都扫一遍）；
        # 缓存 60s，页面显示可接受最多 1 分钟滞后
        _stats_key = 'backup:uploads_stats'
        _stats = _bk_cache.get(_stats_key)
        if _stats is None:
            _stats = [0, 0]
            for root, _, files in os.walk(uploads_dir):
                _stats[0] += len(files)
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        _stats[1] += os.path.getsize(fp)
            _bk_cache.set(_stats_key, _stats, timeout=60)
        uploads_count, uploads_size = _stats

    # Python 孤儿文件统计（DB 已无引用的 python_answers/python_files
    # 残留 + 历史遗留目录 uploads/python）——两次 dirlist + os.walk 全量
    # 扫盘，与 uploads 统计同样 60s 缓存
    _orphan = _bk_cache.get('backup:orphan_stats')
    if _orphan is None:
        _orphan = _scan_python_orphans()
        _bk_cache.set('backup:orphan_stats', _orphan, timeout=60)
    orphan_count, orphan_bytes = _orphan

    return render_template('admin_backup.html', db_size=db_size,
                           uploads_count=uploads_count, uploads_size=uploads_size,
                           orphan_count=orphan_count, orphan_bytes=orphan_bytes)


@homework_bp.route('/admin/backup/download', methods=['POST'])
@admin_login_required
def admin_backup_download():
    """下载数据库备份（ZIP含 PostgreSQL 转储 SQL + 目录清单）"""
    import subprocess  # nosec B404 - 固定参数列表调用管理员配置的 pg_dump
    from app.config import Config

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # 使用解析后的绝对路径，避免 PATH 中同名恶意程序劫持。
    pg_dump = shutil.which('pg_dump')
    if not pg_dump:
        return '服务器未安装 pg_dump，无法创建数据库备份', 503

    # 执行 pg_dump
    pg_pass = Config.DB_PASS
    try:
        result = subprocess.run([  # nosec B603 - 无 shell，参数均为独立 argv
            pg_dump, '-h', Config.DB_HOST, '-p', Config.DB_PORT,
            '-U', Config.DB_USER, '-d', Config.DB_NAME,
            '--no-owner', '--no-acl', '--format=plain'
        ], capture_output=True, text=True, timeout=120,
           env={**os.environ, 'PGPASSWORD': pg_pass})
    except subprocess.TimeoutExpired:
        current_app.logger.error('pg_dump 执行超时')
        return '数据库备份超时，请稍后重试', 504

    if result.returncode != 0:
        current_app.logger.error('pg_dump 失败，退出码=%s: %s',
                                 result.returncode, (result.stderr or '')[:500])
        return '数据库备份失败，请检查 PostgreSQL 工具和连接配置', 500
    dump_sql = result.stdout or ''

    def _build(zf):
        zf.writestr('backup.sql', dump_sql)
        # 目录清单
        listing = []
        for d in ['static/uploads', 'static/homework', 'static/submissions', 'static/question_img']:
            dp = os.path.join(base_dir, d)
            if os.path.isdir(dp):
                for root, _, files in os.walk(dp):
                    for f in files:
                        rel = os.path.relpath(os.path.join(root, f), base_dir)
                        listing.append(rel.replace('\\', '/'))
        info = f"Backup time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        info += f"Database: {Config.DB_NAME}\nHost: {Config.DB_HOST}:{Config.DB_PORT}\n\n"
        info += "File listing:\n" + '\n'.join(sorted(listing))
        zf.writestr('backup_info.txt', info)

    return send_temp_zip(_build, f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
