"""
班级与学生管理蓝图
功能：班级CRUD、学生导入/管理、密码重置、学习小组管理
"""
from flask import Blueprint, request, render_template, redirect, url_for, session, flash, jsonify, send_file
from flask import current_app
from datetime import datetime
from io import BytesIO
import os
from sqlalchemy import text
from sqlalchemy.orm import joinedload, selectinload
from app.extensions import db, cache
from app.models import (Class, Student, StudyGroup, Log, GroupFile, GroupJoinRequest,
                         Result, Appeal, HomeworkSubmission, PythonAnswer,
                         ResourceQuizResult, AIChatMessage, StudentAIConfig,
                         SurveyAnswer, Teacher,
                         StudentWork, WorkEvaluation, StudentDriveFile, ExamAttempt,
                         AttendanceRecord, StudentDriveQuota, ClassroomSetting,
                         TeachingSession)
from app.decorators import admin_login_required, login_required
from app.utils import (get_classes_cached, invalidate_lookup_cache, parse_int,
                       generate_numeric_password, paginate_query, excel_safe,
                       get_client_ip, student_login_clear_throttle,
                       DEFAULT_GRADE_OPTIONS)
from werkzeug.security import generate_password_hash
from app.schemas import (
    ClassCreate, ClassUpdate, StudentCreate, StudentUpdate,
    StudentPasswordReset, GroupCreate, GroupUpdate, validate_form
)
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
import re

class_mgmt_bp = Blueprint('class_management', __name__, url_prefix='')


def _parse_id_csv(ids_str):
    """解析逗号分隔的 ID 字符串为 int 列表，静默过滤非数字元素。

    非数字元素直接 int() 会抛 ValueError → 500，前端表单可能被篡改。
    """
    result = []
    for part in str(ids_str or '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


def _store_secret_notice(message):
    """把一次性密码提示存服务端缓存，避免 Flask 客户端 Session Cookie 携带明文。

    消息内含临时口令明文，缓存后端（filesystem）是磁盘文件——与
    import:pending 暂存一致走凭据加密通道，不以明文落盘。
    """
    import secrets
    from app.credential_crypto import encrypt_secret
    token = secrets.token_urlsafe(24)
    cache.set(f'admin:secret-notice:{token}', encrypt_secret(message), timeout=120)
    return token


def _consume_secret_notice():
    token = request.args.get('secret_notice', '').strip()
    if not token:
        return None
    key = f'admin:secret-notice:{token}'
    message = cache.get(key)
    cache.delete(key)
    if not message:
        return None
    try:
        from app.credential_crypto import decrypt_secret
        return decrypt_secret(message)
    except Exception:
        # 密文无法解密（SECRET_KEY 被更换等）：宁可丢提示也不 500
        return None

# ──────────────────────────────────────────────
#  班级管理
# ──────────────────────────────────────────────


@class_mgmt_bp.route('/admin/classes')
@admin_login_required
def admin_classes():
    """班级管理页面"""
    classes = get_classes_cached()
    return render_template('admin_classes.html', classes=classes)


@class_mgmt_bp.route('/admin/classes/add', methods=['POST'])
@admin_login_required
def add_class():
    """添加班级"""
    ok, result = validate_form(ClassCreate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_classes'))

    existing = Class.query.filter_by(name=result.name).first()
    if existing:
        flash(f'班级 "{result.name}" 已存在', 'danger')
        return redirect(url_for('class_management.admin_classes'))

    new_class = Class(name=result.name, description=result.description or '')
    db.session.add(new_class)
    db.session.add(Log(user_id=0, user_type='admin',
                       action='添加班级', detail=f'添加班级: {result.name}'))
    db.session.commit()
    invalidate_lookup_cache('classes')
    flash(f'班级 "{result.name}" 添加成功', 'success')
    return redirect(url_for('class_management.admin_classes'))


@class_mgmt_bp.route('/admin/classes/<int:class_id>/edit', methods=['POST'])
@admin_login_required
def edit_class(class_id):
    """编辑班级"""
    cls = db.get_or_404(Class, class_id)
    ok, result = validate_form(ClassUpdate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_classes'))

    existing = Class.query.filter(Class.name == result.name, Class.id != class_id).first()
    if existing:
        flash(f'班级 "{result.name}" 已存在', 'danger')
        return redirect(url_for('class_management.admin_classes'))

    old_name = cls.name
    cls.name = result.name
    cls.description = result.description or ''
    propagate_class_rename(cls.id, old_name, result.name)
    db.session.commit()
    invalidate_lookup_cache('classes')
    flash(f'班级 "{result.name}" 更新成功', 'success')
    return redirect(url_for('class_management.admin_classes'))


def propagate_class_rename(class_id, old_name, new_name):
    """班级改名时同步按名称引用该班的冗余列（与改名同一事务，调用方提交）。

    课程表 class_schedule 按班级**名称**存储；不同步的话自动切班按新名
    查不到班级 → 上课班级被置空 → 未设上课班级时学生一律无法登录。
    """
    if not old_name or old_name == new_name:
        return
    from app.models import ClassSchedule
    ClassSchedule.query.filter_by(class_name=old_name).update(
        {ClassSchedule.class_name: new_name}, synchronize_session=False)
    Student.query.filter_by(class_id=class_id).update(
        {Student.student_class: new_name}, synchronize_session=False)


@class_mgmt_bp.route('/admin/classes/<int:class_id>/delete', methods=['POST'])
@admin_login_required
def delete_class(class_id):
    """删除班级（含所有学生和小组）"""
    cls = db.get_or_404(Class, class_id)
    student_count = Student.query.filter_by(class_id=class_id).count()
    # 收集小组网盘磁盘文件路径（按组，含非本班学生上传者；DB 提交成功后删除）
    group_disk_paths = []
    stu_sub_ids, stu_disk_paths = [], []
    try:
        if student_count > 0:
            student_ids = [s.id for s in Student.query.filter_by(class_id=class_id).all()]
            # 统一清理学生引用（磁盘路径一并收集，commit 成功后统删；
            # 此前缺陷：delete_class 只删 DB 行，学生网盘/作品/Python 答案/
            # 作业提交目录全部残留磁盘孤儿）
            stu_sub_ids, stu_disk_paths = _cleanup_student_records_batch(student_ids)

        # 班级级关联清理（无论班级是否有学生均执行，避免孤儿记录导致删除失败）：
        # 先删子表引用，再删主表
        group_ids = [g.id for g in StudyGroup.query.filter_by(class_id=class_id).all()]
        # 学生 group_id 仍指向即将删除的小组（FK 无级联）：必须先置空，
        # 否则有小组成员的班级删除必失败
        Student.query.filter(Student.class_id == class_id,
                             Student.group_id.isnot(None)).update(
            {Student.group_id: None}, synchronize_session=False)
        if group_ids:
            group_disk_paths = [gf.file_path for gf in GroupFile.query.filter(
                GroupFile.group_id.in_(group_ids)).all() if gf.file_path]
            for gid in group_ids:
                GroupFile.query.filter_by(group_id=gid).delete()
                GroupJoinRequest.query.filter(GroupJoinRequest.group_id == gid).delete(synchronize_session=False)
        StudyGroup.query.filter_by(class_id=class_id).delete()
        AttendanceRecord.query.filter(AttendanceRecord.class_id == class_id).delete(synchronize_session=False)
        StudentDriveQuota.query.filter(StudentDriveQuota.class_id == class_id).delete(synchronize_session=False)
        from app.models import TeacherAIShare
        TeacherAIShare.query.filter_by(class_id=class_id).delete(
            synchronize_session=False)
        # 作业-班级多对多关联表（ORM 无级联，需手动清理）
        db.session.execute(text('DELETE FROM homework_classes WHERE class_id = :cid'), {'cid': class_id})

        # 解除 classroom_setting.active_class_id 对该班级的引用（删除当前上课班级时必需）
        ClassroomSetting.query.filter_by(active_class_id=class_id).update(
            {ClassroomSetting.active_class_id: None}, synchronize_session=False)
        from app.models import ClassroomSession
        ClassroomSession.query.filter_by(class_id=class_id).delete(
            synchronize_session=False)
        TeachingSession.query.filter_by(class_id=class_id).update(
            {TeachingSession.class_id: None}, synchronize_session=False)

        # 删除学生（班级级清理完成后再删学生，保证子表先于主表）
        if student_count > 0:
            Student.query.filter_by(class_id=class_id).delete()

        # 8. 删除班级
        db.session.delete(cls)
        db.session.commit()
        invalidate_lookup_cache('classes')
        flash(f'班级 "{cls.name}" 及其 {student_count} 名学生已删除', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除班级 {class_id} 失败: {e}', exc_info=True)
        flash('删除班级失败，请先清理该班级的关联数据后重试', 'danger')
        return redirect(url_for('class_management.admin_classes'))
    # DB 提交成功后再删磁盘文件（学生提交目录/网盘/作品/答案 + 小组网盘，
    # 尽力而为，失败仅残留孤儿；commit 失败回滚时文件不能已删）
    _cleanup_student_disk_files(stu_sub_ids, stu_disk_paths)
    if group_disk_paths:
        try:
            from app.utils import delete_file_from_disk as _delete_file
            for rel in group_disk_paths:
                try:
                    _delete_file(rel)
                except Exception:
                    pass
        except Exception:
            current_app.logger.warning('删除班级小组文件磁盘清理失败（忽略）', exc_info=True)
    return redirect(url_for('class_management.admin_classes'))


# ──────────────────────────────────────────────
#  学生管理
# ──────────────────────────────────────────────

@class_mgmt_bp.route('/admin/students')
@admin_login_required
def admin_students():
    """学生管理页面 — 分页、排序、班级筛选"""
    sort_by = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')
    class_id = request.args.get('class_id', '', type=str)
    search = request.args.get('search', '', type=str)
    status = request.args.get('status', '', type=str)

    query = Student.query.options(
        joinedload(Student.class_), joinedload(Student.group))

    cid = parse_int(class_id)
    if cid is not None:
        query = query.filter_by(class_id=cid)
    if search:
        query = query.filter(
            db.or_(
                Student.name.contains(search),
                Student.student_number.contains(search),
                Student.student_class.contains(search)
            )
        )
    if status == 'activated':
        query = query.filter_by(is_activated=True)
    elif status == 'deactivated':
        query = query.filter_by(is_activated=False)

    allowed_sort_fields = {
        'id', 'name', 'student_number', 'student_class', 'class_id',
        'group_id', 'is_activated', 'login_time',
    }
    if sort_by not in allowed_sort_fields:
        sort_by = 'id'
    sort_column = getattr(Student, sort_by)
    if order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    pagination = paginate_query(query)
    students = pagination.items
    classes = get_classes_cached()
    # 编辑弹窗的小组下拉（按班级过滤由前端联动，此处全量提供即可；
    # 组数量级小，无需分页）
    groups = StudyGroup.query.order_by(StudyGroup.class_id, StudyGroup.name).all()

    return render_template('admin_students.html',
                           students=students,
                           classes=classes,
                           groups=groups,
                           pagination=pagination,
                           sort=sort_by,
                           order=order,
                           class_id=class_id,
                           search=search,
                           status=status,
                           secret_notice=_consume_secret_notice())


@class_mgmt_bp.route('/admin/students/add', methods=['POST'])
@admin_login_required
def add_student():
    """添加单个学生"""
    ok, result = validate_form(StudentCreate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_students'))

    if result.student_number:
        existing = Student.query.filter_by(student_number=result.student_number).first()
        if existing:
            flash(f'学号 {result.student_number} 已存在', 'danger')
            return redirect(url_for('class_management.admin_students'))

    student = Student(
        name=result.name,
        # 空学号以 NULL 入库（此前用 ''，uq_student_number 唯一约束对空串
        # 同样生效——连续添加两个不填学号的学生会 IntegrityError → 500）
        student_number=result.student_number or None,
        student_class=result.student_class or '',
        class_id=result.class_id,
        grade=request.form.get('grade', '').strip(),
        is_activated=True,
        has_changed_password=False
    )
    pwd = result.password.strip() if result.password else generate_numeric_password()
    if len(pwd) < 6:
        flash('初始密码长度至少6位', 'danger')
        return redirect(url_for('class_management.admin_students'))
    # 初始密码只在本次响应中展示，不落盘保存明文。
    student.set_password(pwd)

    db.session.add(student)
    db.session.commit()
    invalidate_lookup_cache('classes')
    token = _store_secret_notice(f'学生“{result.name}”添加成功，初始密码：{pwd}')
    return redirect(url_for('class_management.admin_students', secret_notice=token))


@class_mgmt_bp.route('/admin/students/<int:student_id>/edit', methods=['POST'])
@admin_login_required
def edit_student(student_id):
    """编辑学生信息"""
    student = db.get_or_404(Student, student_id)
    ok, result = validate_form(StudentUpdate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_students'))

    if result.student_number and result.student_number != student.student_number:
        existing = Student.query.filter_by(student_number=result.student_number).first()
        if existing and existing.id != student_id:
            flash(f'学号 {result.student_number} 已被占用', 'danger')
            return redirect(url_for('class_management.admin_students'))

    # 小组归属校验：禁止把学生加入其他班级的小组
    if result.group_id:
        grp = db.session.get(StudyGroup, result.group_id)
        if not grp or grp.class_id != result.class_id:
            flash('所选小组与该学生的班级不匹配，请选择本班小组', 'danger')
            return redirect(url_for('class_management.admin_students'))

    student.name = result.name
    # 空学号以 NULL 入库（与添加分支一致；此前存 ''，uq_student_number 唯一
    # 约束把多个空串视为同一值 → 清空学号后编辑其他空学号学生必 500）
    student.student_number = result.student_number or None
    student.student_class = result.student_class or ''
    student.class_id = result.class_id
    student.group_id = result.group_id
    student.grade = request.form.get('grade', '').strip()
    student.is_activated = request.form.get('is_activated', '') == 'true'
    db.session.commit()
    invalidate_lookup_cache('classes')
    flash(f'学生 "{result.name}" 信息更新成功', 'success')
    return redirect(url_for('class_management.admin_students'))


def _cleanup_student_records(student_id):
    """删除单个学生前清理外键引用（薄包装，兼容既有调用）。"""
    return _cleanup_student_records_batch([student_id])


def _cleanup_student_records_batch(student_ids):
    """批量删除学生前清理所有外键引用，避免 commit 时 IntegrityError → 500。

    与 delete_class 的级联清理保持一致。
    全部按 id 集合一次执行，批量删除 50 人从 14×50 次 DB 往返降为 14 次。

    只做 DB 部分；返回 (sub_ids, disk_paths) 供调用方在 **commit 成功后**
    调 _cleanup_student_disk_files 做磁盘清理——磁盘删除发生在 commit 前
    时，commit 失败回滚后学生记录仍在而文件已删（记录悬空）。
    """
    if not student_ids:
        return [], []
    sub_ids = [r.id for r in HomeworkSubmission.query.filter(
        HomeworkSubmission.student_id.in_(student_ids)).all()]
    disk_paths = []
    for model, col in ((StudentDriveFile, StudentDriveFile.file_path),
                       (StudentWork, StudentWork.file_path),
                       (PythonAnswer, PythonAnswer.file_path)):
        disk_paths += [p for (p,) in model.query.with_entities(col).filter(
            model.student_id.in_(student_ids)).all() if p]
    # 小组文件按 uploader_id（字段名与 student_id 不同，单独收集）
    disk_paths += [p for (p,) in GroupFile.query.with_entities(
        GroupFile.file_path).filter(
        GroupFile.uploader_id.in_(student_ids)).all() if p]
    # 1. 删除依赖 student 的记录
    Result.query.filter(Result.student_id.in_(student_ids)).delete(synchronize_session=False)
    Appeal.query.filter(Appeal.student_id.in_(student_ids)).delete(synchronize_session=False)
    HomeworkSubmission.query.filter(HomeworkSubmission.student_id.in_(student_ids)).delete(synchronize_session=False)
    PythonAnswer.query.filter(PythonAnswer.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 分析短缓存按资源失效：学生答卷行删除后，相关资源的统计必须重算
    quiz_resource_ids = [rid for (rid,) in ResourceQuizResult.query.with_entities(
        ResourceQuizResult.resource_id).filter(
        ResourceQuizResult.student_id.in_(student_ids)).distinct().all()]
    ResourceQuizResult.query.filter(ResourceQuizResult.student_id.in_(student_ids)).delete(synchronize_session=False)
    if quiz_resource_ids:
        from app.services import quiz_analysis_cache
        for rid in quiz_resource_ids:
            quiz_analysis_cache.invalidate_analysis(rid)
    # 问卷答卷（survey_answer.student_id FK 无级联，答过问卷的学生删除必 500）
    SurveyAnswer.query.filter(SurveyAnswer.student_id.in_(student_ids)).delete(synchronize_session=False)
    AIChatMessage.query.filter(AIChatMessage.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 学生 AI 配置（此前遗漏：学生配置过 AI 后删除必 500）
    StudentAIConfig.query.filter(StudentAIConfig.student_id.in_(student_ids)).delete(synchronize_session=False)
    GroupJoinRequest.query.filter(GroupJoinRequest.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 学生上传的小组文件（uploader_id FK NOT NULL 无级联，此前遗漏：上传过即删除必 500）
    GroupFile.query.filter(GroupFile.uploader_id.in_(student_ids)).delete(synchronize_session=False)
    # 学习活动作品 + 作品评价（bulk delete 不触发 ORM 级联，先删评价再删作品）
    work_ids = [w.id for w in StudentWork.query.filter(
        StudentWork.student_id.in_(student_ids)).all()]
    if work_ids:
        WorkEvaluation.query.filter(WorkEvaluation.work_id.in_(work_ids)).delete(synchronize_session=False)
    StudentWork.query.filter(StudentWork.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 个人网盘文件记录
    StudentDriveFile.query.filter(StudentDriveFile.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 考试进行中记录（此前遗漏：学生打开过考试页则删除必 500）
    ExamAttempt.query.filter(ExamAttempt.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 签到记录（此前遗漏：AttendanceRecord.student_id 指向学生，删除必 500）
    AttendanceRecord.query.filter(AttendanceRecord.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 网盘容量覆盖（学生级，此前遗漏）
    StudentDriveQuota.query.filter(StudentDriveQuota.student_id.in_(student_ids)).delete(synchronize_session=False)
    # 2. 解除 student 作为组长的引用。
    # 注意不能再按学生 id 清 graded_by：该列现存的是**教师** id（旧的
    # 指向 student 的外键已由 migrate_db 删除），按学生 id 置空会抹掉
    # 同 id 教师的批改人记录
    StudyGroup.query.filter(StudyGroup.leader_id.in_(student_ids)).update(
        {StudyGroup.leader_id: None}, synchronize_session=False)
    return sub_ids, disk_paths


def _cleanup_student_disk_files(sub_ids, disk_paths):
    """删除学生的磁盘文件清理（尽力而为，失败仅告警不中断）。

    必须在 DB commit 成功之后调用：先删文件后 commit 的顺序一旦 commit
    失败回滚，学生记录仍在而提交目录/网盘/作品/答案文件已删（悬空记录）。
    """
    if not sub_ids and not disk_paths:
        return
    import shutil as _shutil
    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        submission_root = os.path.join(_BASE, 'static', 'submissions')
        for sub_id in sub_ids:
            sub_dir = os.path.join(submission_root, str(sub_id))
            if os.path.isdir(sub_dir):
                _shutil.rmtree(sub_dir, ignore_errors=True)
        from app.utils import delete_file_from_disk as _delete_file
        for rel in disk_paths:
            try:
                _delete_file(rel)
            except Exception:
                pass
    except Exception:
        current_app.logger.warning('删除学生磁盘文件清理失败（已忽略）', exc_info=True)


@class_mgmt_bp.route('/admin/students/<int:student_id>/delete', methods=['POST'])
@admin_login_required
def delete_student(student_id):
    """删除单个学生"""
    student = db.get_or_404(Student, student_id)
    name = student.name
    try:
        sub_ids, disk_paths = _cleanup_student_records(student_id)
        db.session.delete(student)
        db.session.commit()
        invalidate_lookup_cache('classes')
        # 磁盘清理放在 commit 成功之后（commit 失败回滚时文件不能已删）
        _cleanup_student_disk_files(sub_ids, disk_paths)
        flash(f'学生 "{name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除学生 {student_id} 失败: {e}', exc_info=True)
        flash('删除学生失败，该学生存在关联数据无法删除，请先清理相关记录', 'danger')
    return redirect(url_for('class_management.admin_students'))


@class_mgmt_bp.route('/admin/students/batch-delete', methods=['POST'])
@admin_login_required
def batch_delete_students():
    """批量删除学生"""
    ids_str = request.form.get('ids', '')
    if not ids_str:
        flash('请选择要删除的学生', 'danger')
        return redirect(url_for('class_management.admin_students'))
    ids = _parse_id_csv(ids_str)
    if ids:
        try:
            sub_ids, disk_paths = _cleanup_student_records_batch(ids)
            Student.query.filter(Student.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            invalidate_lookup_cache('classes')
            # 磁盘清理放在 commit 成功之后（commit 失败回滚时文件不能已删）
            _cleanup_student_disk_files(sub_ids, disk_paths)
            flash(f'已删除 {len(ids)} 名学生', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'批量删除学生失败: {e}', exc_info=True)
            flash('批量删除失败，请重试', 'danger')
    return redirect(url_for('class_management.admin_students'))


def _unknown_import_grades(pending):
    """返回导入名单中不在常用/教师/学生已有年级里的值（仅提示，不阻断）。"""
    known = set(DEFAULT_GRADE_OPTIONS)
    known |= {(g or '').strip() for (g,) in db.session.query(Teacher.grade).all()
              if (g or '').strip()}
    known |= {(g or '').strip() for (g,) in db.session.query(Student.grade).all()
              if (g or '').strip()}
    return sorted({p[3] for p in pending if p[3] and p[3] not in known})


@class_mgmt_bp.route('/admin/students/import', methods=['POST'])
@admin_login_required
def import_students():
    """导入学生名单 — 支持文本和Excel，班级直接取自表格中的数据

    性能优化（342 名学生从分钟级降到秒级）：
    - 预加载现有学号/姓名集合与班级映射，消除逐行查重查询（N+1）
    - 批量初始密码只哈希一次（所有学生共用），不再逐人重复 pbkdf2 计算
    - 收集后统一 add_all + 单次 commit

    同名同班处理：真实存在同名同班学生（不同学号），不一律跳过——
    首次导入检测到冲突时暂存并返回确认请求，由管理员决定导入还是跳过。
    """
    confirm_token = request.form.get('confirm_token', '').strip()
    import_mode = request.form.get('import_mode', 'text')
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

    # ── 确认阶段：管理员确认后按暂存数据执行导入（含同名同班）──
    if confirm_token:
        from app.extensions import cache as _import_cache
        from app.credential_crypto import decrypt_secret as _dec
        stash = _import_cache.get(f'import:pending:{confirm_token}')
        if not stash:
            flash('确认会话已过期（10 分钟），请重新导入', 'danger')
            return redirect(url_for('class_management.admin_students'))
        _import_cache.delete(f'import:pending:{confirm_token}')
        pending = stash['pending']
        batch_password = _dec(stash['batch_password'])
        dup_total = stash.get('duplicates_total', 0)
        imported = len(pending)
        if pending:
            pw_hash = generate_password_hash(batch_password, method='pbkdf2:sha256')
            students = [Student(
                name=p[0], student_number=p[1] or None, student_class=p[2],
                class_id=p[4], grade=p[3], is_activated=True,
                has_changed_password=False, password_hash=pw_hash
            ) for p in pending]
            db.session.add_all(students)
            try:
                db.session.commit()
                invalidate_lookup_cache('classes')
            except Exception as e:
                # 确认提交失败时回滚并给出友好提示（暂存 class_id 失效等场景）
                db.session.rollback()
                current_app.logger.error(f'确认导入失败: {e}', exc_info=True)
                flash('导入确认失败，请重新导入', 'danger')
                return redirect(url_for('class_management.admin_students'))
        msg = f'成功导入 {imported} 名学生（本批临时密码: {batch_password}，请通知学生登录后立即修改）'
        if dup_total:
            msg += f'，其中 {dup_total} 名为同名同班（已按确认导入）'
        unknown_grades = _unknown_import_grades(pending)
        if unknown_grades:
            msg += ('；注意：年级 ' + '、'.join(unknown_grades) +
                    ' 不在常用年级/教师账号中，按年级授权可能不匹配')
        token = _store_secret_notice(msg)
        redirect_url = url_for('class_management.admin_students', secret_notice=token)
        if wants_json:
            return jsonify({'success': True, 'redirect': redirect_url,
                            'message': msg})
        return redirect(redirect_url)

    imported = 0
    skipped = 0
    errors = []
    duplicates = []  # 同名同班冲突：{name, student_class, number}
    batch_password = generate_numeric_password()

    # 预加载现有数据（一次查询替代逐行 filter_by）
    existing_numbers = {
        r[0] for r in db.session.query(Student.student_number).all() if r[0]
    }
    existing_name_class = {
        (s.name, s.student_class) for s in Student.query.with_entities(
            Student.name, Student.student_class).all()
    }
    classes_map = {c.name: c.id for c in Class.query.all()}

    def get_or_create_class(class_name):
        """查找班级，不存在则自动创建（使用预加载映射）"""
        if not class_name:
            return None
        cid = classes_map.get(class_name)
        if cid is None:
            cls = Class(name=class_name, description='导入时自动创建')
            db.session.add(cls)
            db.session.flush()
            classes_map[class_name] = cls.id
            cid = cls.id
        return cid

    # 收集待导入学生：(name, student_number, class_name, grade, class_id)
    pending = []

    if import_mode == 'text':
        text_data = request.form.get('text_data', '')
        if not text_data.strip():
            flash('请输入学生名单', 'danger')
            return redirect(url_for('class_management.admin_students'))
        for line_num, line in enumerate(text_data.strip().split('\n'), 1):
            line = line.strip()
            if not line:
                continue
            parts = re.split(r'[\s,，]+', line)
            if len(parts) < 1:
                continue
            # 格式: 学号 姓名 班级 年级
            student_number = parts[0] if len(parts) >= 1 else ''
            name = parts[1] if len(parts) >= 2 else ''
            text_class = parts[2] if len(parts) >= 3 else ''
            grade = parts[3] if len(parts) >= 4 else ''
            if not name or not text_class:
                errors.append(f'第{line_num}行: 姓名和班级不能为空')
                continue
            if student_number:
                if student_number in existing_numbers:
                    errors.append(f'第{line_num}行: 学号 {student_number} 已存在')
                    skipped += 1
                    continue
            if (name, text_class) in existing_name_class:
                # 同名同班：不直接跳过——列入冲突清单，且暂入 pending，
                # 由管理员确认后决定是否导入（确实存在同名同班学生）
                duplicates.append({'name': name, 'student_class': text_class,
                                   'number': student_number})
                cid = get_or_create_class(text_class)
                pending.append((name, student_number, text_class, grade, cid))
                # 同样登记学号：否则后面同学号的行会通过校验，确认导入时
                # 撞唯一约束整批失败
                if student_number:
                    existing_numbers.add(student_number)
                skipped += 1
                continue
            cid = get_or_create_class(text_class)
            pending.append((name, student_number, text_class, grade, cid))
            # 本批内去重
            if student_number:
                existing_numbers.add(student_number)
            existing_name_class.add((name, text_class))
            imported += 1

    elif import_mode == 'excel':
        if 'excel_file' not in request.files:
            flash('请选择Excel文件', 'danger')
            return redirect(url_for('class_management.admin_students'))
        file = request.files['excel_file']
        if not file.filename:
            flash('请选择Excel文件', 'danger')
            return redirect(url_for('class_management.admin_students'))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                flash('Excel文件为空', 'danger')
                return redirect(url_for('class_management.admin_students'))
            for row_num, row in enumerate(rows, 1):
                if row_num == 1:
                    first_cell = str(row[0]).strip() if row[0] else ''
                    if first_cell in ('学号', '姓名', 'name', '学生姓名'):
                        continue
                if not row or not row[1]:
                    continue
                # 列序: A=学号, B=姓名, C=班级, D=年级(选填)
                student_number = str(row[0]).strip() if row[0] else ''
                name = str(row[1]).strip() if len(row) >= 2 and row[1] else ''
                text_class = str(row[2]).strip() if len(row) >= 3 and row[2] else ''
                grade = str(row[3]).strip() if len(row) >= 4 and row[3] else ''
                if not name or not text_class:
                    errors.append(f'第{row_num}行: 姓名和班级不能为空')
                    continue
                if student_number:
                    if student_number in existing_numbers:
                        errors.append(f'第{row_num}行: 学号 {student_number} 已存在')
                        skipped += 1
                        continue
                if (name, text_class) in existing_name_class:
                    # 同名同班：不直接跳过——列入冲突清单，且暂入 pending，
                    # 由管理员确认后决定是否导入（确实存在同名同班学生）
                    duplicates.append({'name': name, 'student_class': text_class,
                                       'number': student_number})
                    cid = get_or_create_class(text_class)
                    pending.append((name, student_number, text_class, grade, cid))
                    if student_number:
                        existing_numbers.add(student_number)
                    skipped += 1
                    continue
                cid = get_or_create_class(text_class)
                pending.append((name, student_number, text_class, grade, cid))
                if student_number:
                    existing_numbers.add(student_number)
                existing_name_class.add((name, text_class))
                imported += 1
            wb.close()
        except Exception:
            db.session.rollback()
            flash('Excel解析失败', 'danger')
            return redirect(url_for('class_management.admin_students'))

    # ── 同名同班冲突：暂存解析结果，返回确认请求（前端弹窗由管理员决定）──
    # 即使全部行都冲突也需询问，否则整份名单被静默跳过
    if duplicates:
        # 提交本批自动创建的班级：否则请求结束会话回滚后班级不落库，
        # 而暂存的 pending 元组中 class_id 指向已回滚的 ID，确认阶段
        # 提交学生时将 FK IntegrityError → 500（此前缺陷）
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        import secrets as _secrets
        from app.extensions import cache as _import_cache
        from app.credential_crypto import encrypt_secret as _enc
        confirm_token = _secrets.token_hex(16)
        # batch_password 用凭据加密通道落缓存：Flask-Caching filesystem 后端
        # 是磁盘明文文件，明文暂存初始口令与 admin_account.txt 的 ACL 收紧
        # 标准不一致（确认阶段取用时解密，展示语义不变）
        _import_cache.set(f'import:pending:{confirm_token}',
                          {'pending': pending,
                           'batch_password': _enc(batch_password),
                           'duplicates_total': len(duplicates)},
                          timeout=600)
        return jsonify({
            'success': True,
            'need_confirm': True,
            'token': confirm_token,
            'duplicates': duplicates[:20],
            'duplicates_total': len(duplicates),
            'imported': len(pending),
        })

    # 批量创建：同一批次密码只哈希一次（pbkdf2 为慢哈希，逐人重复是
    # 342 名学生导入耗时数分钟的主要瓶颈），统一 add_all + 单次 commit
    students = []
    if pending:
        pw_hash = generate_password_hash(batch_password, method='pbkdf2:sha256')
        for (name, student_number, text_class, grade, cid) in pending:
            students.append(Student(
                name=name, student_number=student_number or None,
                student_class=text_class, class_id=cid,
                grade=grade, is_activated=True, has_changed_password=False,
                password_hash=pw_hash
            ))
    if students:
        db.session.add_all(students)

    try:
        db.session.commit()
        invalidate_lookup_cache('classes')
    except Exception:
        db.session.rollback()
        flash('导入失败', 'danger')
        return redirect(url_for('class_management.admin_students'))

    msg = f'成功导入 {imported} 名学生（本批临时密码: {batch_password}，请通知学生登录后立即修改）'
    if skipped:
        msg += f'，跳过 {skipped} 名重复'
    unknown_grades = _unknown_import_grades(pending)
    if unknown_grades:
        msg += ('；注意：年级 ' + '、'.join(unknown_grades) +
                ' 不在常用年级/教师账号中，按年级授权可能不匹配')
    if errors:
        msg += f'，{len(errors)} 个错误'
        for err in errors[:5]:
            flash(err, 'warning')
    token = _store_secret_notice(msg)
    redirect_url = url_for('class_management.admin_students', secret_notice=token)
    if wants_json:
        return jsonify({'success': True, 'redirect': redirect_url,
                        'message': msg})
    return redirect(redirect_url)


# ──────────────────────────────────────────────
#  密码管理
# ──────────────────────────────────────────────

@class_mgmt_bp.route('/admin/students/<int:student_id>/reset-password', methods=['POST'])
@admin_login_required
def reset_student_password(student_id):
    """重置单个学生密码"""
    student = db.get_or_404(Student, student_id)
    ok, result = validate_form(StudentPasswordReset, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_students'))

    # 密码仅通过服务端一次性通知展示，不写入 Session Cookie 或数据库明文字段。
    student.set_password(result.new_password)
    student.has_changed_password = False
    db.session.commit()
    # 管理员重置密码即解除该生登录封锁（学号/姓名维度 + 最近 IP），
    # 学生拿到新密码后可立即重新登录，无需等待原锁定倒计时
    student_login_clear_throttle(
        student.student_number, student.name,
        [student.ip_address, get_client_ip()])
    token = _store_secret_notice(
        f'学生“{student.name}”密码已重置为：{result.new_password}'
    )
    return redirect(url_for('class_management.admin_students', secret_notice=token))


@class_mgmt_bp.route('/admin/students/batch-reset-password', methods=['POST'])
@admin_login_required
def batch_reset_student_password():
    """批量重置学生密码"""
    ids_str = request.form.get('ids', '')
    new_password = request.form.get('new_password', '').strip()
    if not ids_str:
        flash('请选择要重置密码的学生', 'danger')
        return redirect(url_for('class_management.admin_students'))
    if len(new_password) < 6:
        flash('新密码长度至少6位', 'danger')
        return redirect(url_for('class_management.admin_students'))
    # 上限 50 字符（与改密/API 版一致）：超长输入对 pbkdf2 造成无谓 CPU 开销
    if len(new_password) > 50:
        flash('新密码长度不能超过50位', 'danger')
        return redirect(url_for('class_management.admin_students'))

    ids = _parse_id_csv(ids_str)
    # 同一批次密码只哈希一次（与上方 Excel 批量导入同一策略）：pbkdf2 为
    # 慢哈希（默认迭代数百毫秒），逐生 set_password 会让 300+ 人选批量重置
    # 阻塞请求线程数分钟；批内密码本就相同，复用同一加盐哈希无额外风险
    pw_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
    count = 0
    reset_students = []
    for sid in ids:
        student = db.session.get(Student, sid)
        if student:
            # 批量重置密码不存储明文。
            student.password_hash = pw_hash
            student.has_changed_password = False
            reset_students.append(
                (student.student_number, student.name, student.ip_address))
            count += 1
    db.session.commit()
    # 批量重置同样解除每名学生的登录封锁，避免“密码已重置但仍被锁定”
    admin_ip = get_client_ip()
    for number, name, last_ip in reset_students:
        student_login_clear_throttle(
            number, name, [last_ip, admin_ip])
    token = _store_secret_notice(f'已重置 {count} 名学生的密码为：{new_password}')
    return redirect(url_for('class_management.admin_students', secret_notice=token))


# ──────────────────────────────────────────────
#  学习小组管理
# ──────────────────────────────────────────────

@class_mgmt_bp.route('/admin/groups')
@admin_login_required
def admin_groups():
    """学习小组管理页面"""
    class_id = request.args.get('class_id', '', type=str)
    classes = get_classes_cached()
    groups = []
    selected_class = None
    cid = parse_int(class_id)
    if cid is not None:
        selected_class = db.session.get(Class, cid)
        if selected_class:
            # joinedload(leader)：模板访问 group.leader.name；
            # selectinload(members/files)：模板对每组做 members|length、
            # members[:10]、files|list（含逐文件求和），整集合必须取出——
            # 每组 2 条懒加载 SQL 改为全页各 1 条（小组数无分页，A-J 最多 10 组）
            groups = StudyGroup.query.options(
                joinedload(StudyGroup.leader),
                selectinload(StudyGroup.members),
                selectinload(StudyGroup.files)
            ).filter_by(class_id=cid).order_by(StudyGroup.name).all()
    return render_template('admin_groups.html',
                           classes=classes,
                           groups=groups,
                           selected_class=selected_class,
                           class_id=class_id)


@class_mgmt_bp.route('/admin/groups/add', methods=['POST'])
@admin_login_required
def add_group():
    """添加学习小组"""
    ok, result = validate_form(GroupCreate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_groups', class_id=request.form.get('class_id', '')))

    existing = StudyGroup.query.filter_by(name=result.name, class_id=result.class_id).first()
    if existing:
        flash(f'小组 "{result.name}" 在该班级已存在', 'danger')
        return redirect(url_for('class_management.admin_groups', class_id=result.class_id))

    # 组长必须属于小组所在班级（此前缺失校验，可造出组长跨班的脏数据，
    # 与 api_create_group 的 _validate_leader 行为对齐）
    if result.leader_id:
        leader = db.session.get(Student, result.leader_id)
        if leader is None:
            flash('组长不存在', 'danger')
            return redirect(url_for('class_management.admin_groups', class_id=result.class_id))
        if leader.class_id != result.class_id:
            flash('组长必须属于该小组所在班级', 'danger')
            return redirect(url_for('class_management.admin_groups', class_id=result.class_id))

    group = StudyGroup(
        name=result.name,
        class_id=result.class_id,
        leader_id=result.leader_id
    )
    db.session.add(group)
    db.session.flush()
    # 组长自动加入小组
    if result.leader_id:
        leader = db.session.get(Student, result.leader_id)
        if leader:
            leader.group_id = group.id
    db.session.commit()
    flash(f'小组 "{result.name}" 创建成功', 'success')
    return redirect(url_for('class_management.admin_groups', class_id=result.class_id))


@class_mgmt_bp.route('/admin/groups/<int:group_id>/edit', methods=['POST'])
@admin_login_required
def edit_group(group_id):
    """编辑学习小组"""
    group = db.get_or_404(StudyGroup, group_id)
    ok, result = validate_form(GroupUpdate, request.form)
    if not ok:
        flash('; '.join(result), 'danger')
        return redirect(url_for('class_management.admin_groups', class_id=group.class_id))

    if result.name:
        dup = StudyGroup.query.filter(
            StudyGroup.name == result.name,
            StudyGroup.class_id == group.class_id,
            StudyGroup.id != group_id
        ).first()
        if dup:
            flash(f'小组 "{result.name}" 在该班级已存在', 'danger')
            return redirect(url_for('class_management.admin_groups', class_id=group.class_id))
        group.name = result.name
    if result.leader_id is not None:
        # 组长必须属于小组所在班级（与 add_group / api_groups._validate_leader
        # 一致）：此前缺失校验，误选外班学生为组长会使其获得本组网盘文件
        # 访问权（student_groups 按 group_id 判权）
        if result.leader_id:
            new_leader = db.session.get(Student, result.leader_id)
            if new_leader is None:
                flash('组长不存在', 'danger')
                return redirect(url_for('class_management.admin_groups', class_id=group.class_id))
            if new_leader.class_id != group.class_id:
                flash('组长必须属于该小组所在班级', 'danger')
                return redirect(url_for('class_management.admin_groups', class_id=group.class_id))
        group.leader_id = result.leader_id
        # 新组长自动加入小组
        if result.leader_id:
            new_leader = db.session.get(Student, result.leader_id)
            if new_leader and new_leader.group_id != group.id:
                new_leader.group_id = group.id
    db.session.commit()
    flash(f'小组 "{group.name}" 更新成功', 'success')
    return redirect(url_for('class_management.admin_groups', class_id=group.class_id))


@class_mgmt_bp.route('/admin/groups/<int:group_id>/delete', methods=['POST'])
@admin_login_required
def delete_group(group_id):
    """删除学习小组"""
    group = db.get_or_404(StudyGroup, group_id)
    cid = group.class_id
    try:
        # 先清理依赖 group 的子表记录（FK 无级联，不清理会 500）：
        # 1. 小组加入/退出申请
        GroupJoinRequest.query.filter_by(group_id=group_id).delete(synchronize_session=False)
        # 2. 小组网盘文件记录 + 磁盘文件
        upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
        group_files = GroupFile.query.filter_by(group_id=group_id).all()
        for gf in group_files:
            if upload_folder and gf.file_path:
                try:
                    abs_path = os.path.normpath(os.path.join(upload_folder, gf.file_path))
                    if os.path.isfile(abs_path):
                        os.remove(abs_path)
                except OSError:
                    current_app.logger.warning(f'删除小组文件失败（忽略）: {gf.file_path}')
            db.session.delete(gf)
        # 3. 解除学生对该小组的引用，再删小组
        Student.query.filter_by(group_id=group_id).update({'group_id': None})
        db.session.delete(group)
        db.session.commit()
        flash(f'小组 "{group.name}" 已删除', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除小组 {group_id} 失败: {e}', exc_info=True)
        flash('删除小组失败，请稍后重试', 'danger')
    return redirect(url_for('class_management.admin_groups', class_id=cid))


@class_mgmt_bp.route('/admin/groups/<int:group_id>/members', methods=['POST'])
@admin_login_required
def set_group_members(group_id):
    """设置小组成员 — 组长自动纳入且不可移除"""
    group = db.get_or_404(StudyGroup, group_id)
    ids_str = request.form.get('member_ids', '')
    member_ids = _parse_id_csv(ids_str)

    # 组长自动纳入成员列表
    if group.leader_id and group.leader_id not in member_ids:
        member_ids.append(group.leader_id)

    # 成员必须属于小组所在班级（此前缺失校验，可混入其他班学生，
    # 使跨班学生通过 group_id 获得该小组网盘访问权限）
    if member_ids:
        valid_ids = [sid for (sid,) in Student.query.with_entities(
            Student.id).filter(
            Student.id.in_(member_ids),
            Student.class_id == group.class_id).all()]
        skipped = len(member_ids) - len(valid_ids)
        if skipped:
            current_app.logger.warning(
                f'小组成员过滤非本班学生 {skipped} 人: group_id={group_id}')
        member_ids = valid_ids

    # 先清空，再重新分配
    Student.query.filter_by(group_id=group_id).update({'group_id': None})
    if member_ids:
        Student.query.filter(Student.id.in_(member_ids)).update(
            {'group_id': group_id}, synchronize_session=False)
    db.session.commit()
    flash(f'小组 "{group.name}" 成员已更新 ({len(member_ids)} 人)', 'success')
    return redirect(url_for('class_management.admin_groups', class_id=group.class_id))


# ──────────────────────────────────────────────
#  模板下载 & 名单导出
# ──────────────────────────────────────────────


@class_mgmt_bp.route('/admin/students/template')
@admin_login_required
def download_import_template():
    """下载学生导入Excel模板 — 学号/姓名/班级/年级（年级与教师账号对齐）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "学生导入模板"
    headers = ['学号', '姓名', '班级', '年级']
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=12)
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    ws.cell(row=2, column=1, value='2024001')
    ws.cell(row=2, column=2, value='张三')
    ws.cell(row=2, column=3, value='2024级计算机1班')
    ws.cell(row=2, column=4, value='高一')
    ws.cell(row=3, column=1, value='2024002')
    ws.cell(row=3, column=2, value='李四')
    ws.cell(row=3, column=3, value='2024级计算机1班')
    ws.cell(row=3, column=4, value='高一')
    ws.column_dimensions['A'].width = 14
    ws.column_dimensions['B'].width = 12
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 14

    # 年级下拉：内置词表 + 教师账号/学生已有年级。导入的年级应与教师账号
    # 的年级一致，否则按年级授权的资源可能匹配不到。
    existing_teacher_grades = {
        (g or '').strip() for (g,) in db.session.query(Teacher.grade).all()
        if (g or '').strip()}
    existing_student_grades = {
        (g or '').strip() for (g,) in db.session.query(Student.grade).all()
        if (g or '').strip()}
    grade_options = list(DEFAULT_GRADE_OPTIONS) + sorted(
        (existing_teacher_grades | existing_student_grades)
        - set(DEFAULT_GRADE_OPTIONS))
    opts = wb.create_sheet('年级选项')
    for idx, grade in enumerate(grade_options, 1):
        opts.cell(row=idx, column=1, value=grade)
    opts.sheet_state = 'hidden'
    dv = DataValidation(
        type='list',
        formula1=f"'年级选项'!$A$1:$A${len(grade_options)}",
        allow_blank=True)
    dv.promptTitle = '年级'
    dv.prompt = '建议与教师账号的年级一致（如高一/高二/高三）'
    dv.errorTitle = '年级不在列表中'
    dv.error = '请从下拉选项选择；如学校使用自定义年级，可忽略此提示。'
    dv.errorStyle = 'warning'
    dv.showErrorMessage = True
    ws.add_data_validation(dv)
    dv.add('D2:D5000')

    guide = wb.create_sheet('填写说明')
    guide_rows = [
        ('列', '说明'),
        ('学号', '建议填写且唯一；同一学号重复会跳过。'),
        ('姓名', '必填。'),
        ('班级', '必填；班级名称不存在时会自动创建，建议与「班级管理」保持一致。'),
        ('年级', '从下拉选择，建议与教师账号的年级一致（如高一、高二、高三、初一）。'
                 '教师账号只有一个年级；按年级授权的资源以教师年级为准。'),
        ('登录密码', '导入后系统生成统一临时密码，首次登录必须修改。'),
    ]
    for r, (col, desc) in enumerate(guide_rows, 1):
        guide.cell(row=r, column=1, value=col).font = Font(bold=(r == 1))
        guide.cell(row=r, column=2, value=desc)
    guide.column_dimensions['A'].width = 12
    guide.column_dimensions['B'].width = 70

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    return send_file(
        file_stream,
        as_attachment=True,
        download_name='学生导入模板.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@class_mgmt_bp.route('/admin/students/export')
@admin_login_required
def export_students():
    """按班级导出学生名单（不导出任何明文密码）"""
    class_id = request.args.get('class_id', '', type=str)
    query = Student.query
    class_name = '全部班级'
    cid = parse_int(class_id)
    if cid is not None:
        query = query.filter_by(class_id=cid)
        cls = db.session.get(Class, cid)
        class_name = cls.name if cls else '未知班级'

    students = query.order_by(Student.class_id, Student.student_number, Student.name).all()
    classes_map = {c.id: c.name for c in Class.query.all()}

    wb = Workbook()
    ws = wb.active
    ws.title = "学生名单"
    headers = ['序号', '学号', '姓名', '班级', '年级', '初始密码状态', '密码状态', '账号状态', '最后登录']
    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    for i, s in enumerate(students, 1):
        ws.cell(row=i + 1, column=1, value=i)
        ws.cell(row=i + 1, column=2, value=excel_safe(s.student_number or ''))
        ws.cell(row=i + 1, column=3, value=excel_safe(s.name))
        ws.cell(row=i + 1, column=4, value=excel_safe(classes_map.get(s.class_id, s.student_class or '未分班')))
        ws.cell(row=i + 1, column=5, value=excel_safe(s.grade or ''))
        ws.cell(row=i + 1, column=6, value='已修改' if s.has_changed_password else '未修改')
        ws.cell(row=i + 1, column=7, value='是' if s.has_changed_password else '否')
        ws.cell(row=i + 1, column=8, value='已激活' if s.is_activated else '未激活')
        ws.cell(row=i + 1, column=9, value=s.login_time.strftime('%Y-%m-%d %H:%M') if s.login_time else '未登录')

    for col_letter, width in [('A', 6), ('B', 14), ('C', 12), ('D', 20), ('E', 10), ('F', 14), ('G', 10), ('H', 10), ('I', 16)]:
        ws.column_dimensions[col_letter].width = width

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f'学生名单_{class_name}_{datetime.now().strftime("%Y%m%d")}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ──────────────────────────────────────────────
#  JSON API (供 AJAX 调用)
# ──────────────────────────────────────────────

@class_mgmt_bp.route('/api/groups/<int:group_id>/detail')
@admin_login_required
def api_group_detail(group_id):
    """获取小组详情JSON — 组长+组员"""
    group = db.get_or_404(StudyGroup, group_id)
    members = Student.query.filter_by(group_id=group_id).all()
    return jsonify({
        'success': True,
        'data': {
            'id': group.id,
            'name': group.name,
            'leader': {
                'id': group.leader.id,
                'name': group.leader.name,
                'student_number': group.leader.student_number
            } if group.leader else None,
            'members': [{
                'id': m.id,
                'name': m.name,
                'student_number': m.student_number,
                'is_leader': group.leader_id == m.id
            } for m in members],
            'member_count': len(members)
        }
    })


@class_mgmt_bp.route('/api/classes/<int:class_id>/students')
@admin_login_required
def api_class_students(class_id):
    """获取班级学生列表JSON"""
    students = Student.query.filter_by(class_id=class_id).order_by(Student.student_number, Student.name).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': s.id,
            'name': s.name,
            'student_number': s.student_number
        } for s in students]
    })


@class_mgmt_bp.route('/api/students/<int:student_id>/change-password', methods=['POST'])
@login_required
def api_change_password(student_id):
    """学生自行修改密码（需要登录验证是本人）

    原密码猜测限流：IP+学生ID 组合键，与登录限流同一机制
    （会话被窃取后不能无限次暴力猜测旧密码）。
    """
    if not session.get('student_id') or session.get('student_id') != student_id:
        return jsonify({'success': False, 'message': '无权操作'}), 403

    from app.utils import admin_login_blocked_seconds, admin_login_register_failure, admin_login_register_success
    throttle_key = f'pwd-change:{student_id}:{request.remote_addr or ""}'
    blocked = admin_login_blocked_seconds(throttle_key)
    if blocked:
        return jsonify({'success': False, 'message': f'尝试过于频繁，请 {blocked} 秒后再试'}), 429

    student = db.get_or_404(Student, student_id)
    data = request.get_json(force=True, silent=True) or {}
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')

    if not student.check_password(old_pw):
        admin_login_register_failure(throttle_key)
        return jsonify({'success': False, 'message': '原密码错误'}), 400
    if len(new_pw.strip()) < 6:
        return jsonify({'success': False, 'message': '新密码长度至少6位'}), 400
    if len(new_pw.strip()) > 50:
        # 与 schemas.py StudentPasswordReset 的 6-50 约束一致；
        # 超长密码 pbkdf2 哈希耗时线性增长（自伤性 CPU DoS）
        return jsonify({'success': False, 'message': '新密码长度不能超过50位'}), 400

    admin_login_register_success(throttle_key)
    student.set_password(new_pw.strip())
    student.has_changed_password = True
    db.session.commit()
    # 与 HTML 改密路由同口径：解除强制改密、失效会话校验缓存、同步本会话
    # 的密码指纹（否则 10s 缓存里的旧指纹会把本人也登出）
    from app.utils import password_fingerprint
    session.pop('must_change_password', None)
    session['pwd_fp'] = password_fingerprint(student.password_hash)
    cache.delete(f'session:check:{student.id}')
    return jsonify({'success': True, 'message': '密码修改成功'})
