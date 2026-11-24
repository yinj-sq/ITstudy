from datetime import datetime
import json
import math

from flask import (Blueprint, request, render_template, redirect, url_for,
                   session, flash, current_app, abort)
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db, cache
from app.models import (Resource, Log, LearningActivity, StudentWork,
                        WorkEvaluation, ExcellenceThreshold, Class, Student)
from app.decorators import teacher_login_required, authenticated_required
from app.services.student_drive_service import (
    get_preview_type, validate_drive_filename, _discard_orphan)
from app.services.resource_access import (
    teacher_can_edit, teacher_can_view, teacher_visible_resources,
    teacher_can_use_resource, teacher_class_ids, student_can_access_resource)
from app.services.download_pool import send_large_download
from app.utils import (
    delete_file_from_disk,
    safe_inline_mimetype,
    strip_inline_content_disposition,
)


activities_bp = Blueprint('activities', __name__, url_prefix='')


def _teacher_name():
    if session.get('is_admin'):
        return '管理员'
    return session.get('teacher_name') or '教师'


def _parse_activity_time(value):
    """解析表单 datetime-local 输入（'' 或非法 → None 表示不限制）"""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def _parse_activity_capacity(value):
    """解析人数上限（'' 或非法 → None 表示不限制）"""
    if not value:
        return None
    try:
        cap = int(value)
        return cap if cap > 0 else None
    except (TypeError, ValueError):
        return None


def _activity_accepting(activity):
    """活动当前是否处于可提交状态：时间窗内（未设置时间窗则不限）。

    返回 (ok, message)。
    """
    now = datetime.now()
    if activity.start_time and now < activity.start_time:
        return False, f'活动于 {activity.start_time.strftime("%Y-%m-%d %H:%M")} 开始，当前不可提交'
    if activity.end_time and now > activity.end_time:
        return False, f'活动已于 {activity.end_time.strftime("%Y-%m-%d %H:%M")} 截止'
    return True, ''


def _invalidate_study_cache():
    cache.delete('study:resources:student')
    cache.delete('study:resources:classroom')


def _teacher_resource_visible(resource):
    """教师端资源边界：管理员全部可见；教师限自己的资源或只读授权资源。

    资源创建者始终可访问自己的资源（即使暂未开放到课堂）；共享教师仍要求
    show_in_classroom 且只在只读模式可见，避免只读共享资源被用于管理。
    管理员年级×学科授权（或旧 is_public）命中的资源对教师只读可见
    （课堂使用与查看），管理仍由 _teacher_can_manage_resource 限定。
    """
    if session.get('is_admin'):
        return True
    if not session.get('is_teacher') or not resource:
        return False
    if teacher_can_edit(resource, session.get('teacher_id'), False):
        return True
    if not resource.show_in_classroom:
        return False
    if (session.get('teacher_mode') or 'edit') != 'edit' and \
            teacher_can_use_resource(resource, session.get('teacher_id')):
        return True
    return teacher_can_view(resource, session.get('teacher_id'), False,
                            session.get('teacher_mode') or 'edit')


def _teacher_can_manage_resource(resource):
    """活动管理边界：管理员或资源创建者；共享只读教师不得管理活动。

    与 _teacher_resource_visible 的区别：活动管理不要求 show_in_classroom，
    创建者可在资源尚未开放到课堂时先编排活动；课堂使用仍由 show_in_classroom
    单独控制。
    """
    return teacher_can_edit(resource, session.get('teacher_id'),
                            bool(session.get('is_admin')))


def _resource_visible_to_current_user(resource):
    if session.get('is_admin'):
        return True
    if session.get('is_teacher'):
        return _teacher_resource_visible(resource)
    student_id = session.get('student_id')
    if not student_id:
        return False
    student = db.session.get(Student, student_id)
    # 学生可见 = 任课教师范围 + 公开/内置资源
    return student_can_access_resource(resource, student)


def _can_access_work(work):
    if session.get('is_admin'):
        return True
    if session.get('is_teacher'):
        return _teacher_resource_visible(work.activity.resource)
    return bool(session.get('student_id') and session.get('student_id') == work.student_id)


def _teacher_can_grade_work(work):
    """作品数据边界（批改/评价类操作）：作品学生必须属于当前上课班级；
    管理员（is_admin）全部放行。"""
    if session.get('is_admin'):
        return True
    if not _teacher_resource_visible(work.activity.resource):
        return False
    class_ids = teacher_class_ids(session.get('teacher_id'))
    student = db.session.get(Student, work.student_id)
    return bool(student and student.class_id in class_ids)


def _apply_excellence_rule(work):
    threshold = ExcellenceThreshold.query.filter_by(activity_id=work.activity_id).first()
    if not threshold or not work.evaluation:
        return
    grades = {x.strip() for x in (threshold.grade_levels or '').split(',') if x.strip()}
    # 防御性处理：min_score 可能为 None 或旧数据中的 NaN/Infinity
    min_score = threshold.min_score
    if min_score is None or (isinstance(min_score, float) and (math.isnan(min_score) or math.isinf(min_score))):
        min_score = 0
    eval_score = work.evaluation.score
    score_ok = eval_score is not None and not (isinstance(eval_score, float) and (math.isnan(eval_score) or math.isinf(eval_score))) and eval_score >= min_score
    grade_ok = bool(work.evaluation.grade and work.evaluation.grade in grades)
    work.is_excellent = bool(score_ok or grade_ok)


def _sync_activity_lesson_tree(resource, activity_id, old_title=None,
                               new_title=None, remove=False):
    """同步活动改名/删除到课堂章节树。

    仅同步标题仍等于活动旧标题的条目，保留教师在编排器中自定义的展示名；
    删除时移除活动条目并清理变空的章节，避免课堂残留 404 入口。
    """
    if not resource or not resource.lesson_tree:
        return False
    try:
        tree = json.loads(resource.lesson_tree)
    except (TypeError, ValueError):
        return False
    if not isinstance(tree, list):
        return False
    changed = False

    def clean_node(node):
        nonlocal changed
        if not isinstance(node, dict):
            return None
        items = []
        for item in node.get('items', []) or []:
            if (isinstance(item, dict) and item.get('kind') == 'activity'
                    and str(item.get('activity_id') or '') == str(activity_id)):
                if remove:
                    changed = True
                    continue
                if new_title and item.get('title') == old_title:
                    item['title'] = new_title
                    changed = True
            items.append(item)
        node['items'] = items
        children = []
        for child in node.get('children', []) or []:
            cleaned = clean_node(child)
            if cleaned is not None:
                children.append(cleaned)
        node['children'] = children
        if not items and not children:
            return None
        return node

    cleaned_tree = []
    for root in tree:
        cleaned = clean_node(root)
        if cleaned is not None:
            cleaned_tree.append(cleaned)
    if changed:
        resource.lesson_tree = json.dumps(cleaned_tree, ensure_ascii=False)
    return changed



@activities_bp.route('/admin/resources/<int:res_id>/activities')
@activities_bp.route('/teacher/resources/<int:res_id>/activities')
@teacher_login_required
def admin_activities(res_id):
    resource = db.get_or_404(Resource, res_id)
    can_manage = _teacher_can_manage_resource(resource)
    if not can_manage and not _teacher_resource_visible(resource):
        flash('无权查看该资源的学习活动', 'danger')
        return redirect(url_for('activities.teacher_resources'))
    activities = LearningActivity.query.filter_by(resource_id=res_id).order_by(
        LearningActivity.sort_order, LearningActivity.created_at.desc()).all()
    back_url = (url_for('resources.admin_resources')
                if session.get('is_admin')
                else url_for('resources.teacher_resource_library'))
    return render_template('admin_activities.html', resource=resource,
                           activities=activities, can_manage=can_manage,
                           back_url=back_url)


@activities_bp.route('/teacher/resources')
@teacher_login_required
def teacher_resources():
    # 分页渲染（资源累加后避免单页全量加载）
    from app.utils import paginate_query
    mode = session.get('teacher_mode') or 'edit'
    if session.get('is_admin'):
        query = Resource.query.filter_by(show_in_classroom=True)
    else:
        # 编辑模式的活动管理列出本人全部资源（含暂未开放到课堂的资源），
        # 否则教师无法先在资源库编排活动；只读模式仍只列课堂可用资源。
        query = teacher_visible_resources(
            session.get('teacher_id'), is_admin=False,
            mode=mode, classroom=(mode != 'edit'))
    pagination = paginate_query(
        query.order_by(Resource.id.desc()),
        default_per_page=20, max_per_page=100
    )
    resources = pagination.items
    stats = {}
    if resources:
        rows = db.session.query(
            LearningActivity.resource_id,
            func.count(LearningActivity.id)
        ).filter(LearningActivity.resource_id.in_([r.id for r in resources])).group_by(
            LearningActivity.resource_id).all()
        stats = {row[0]: row[1] for row in rows}
    return render_template('teacher_resources.html', resources=resources, stats=stats,
                           pagination=pagination)


@activities_bp.route('/admin/resources/<int:res_id>/activities/new', methods=['GET', 'POST'])
@activities_bp.route('/teacher/resources/<int:res_id>/activities/new', methods=['GET', 'POST'])
@teacher_login_required
def admin_activity_create(res_id):
    resource = db.get_or_404(Resource, res_id)
    if not _teacher_can_manage_resource(resource):
        flash('只有资源创建者可以创建学习活动', 'danger')
        return redirect(url_for('activities.admin_activities', res_id=res_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('活动名称不能为空', 'danger')
            return redirect(url_for('activities.admin_activity_create', res_id=res_id))
        activity = LearningActivity(
            resource_id=res_id,
            title=title,
            description=request.form.get('description', '').strip(),
            require_upload=request.form.get('require_upload') == '1',
            sort_order=request.form.get('sort_order', type=int) or 0,
            is_active=request.form.get('is_active', '1') == '1',
            start_time=_parse_activity_time(request.form.get('start_time', '').strip()),
            end_time=_parse_activity_time(request.form.get('end_time', '').strip()),
            capacity=_parse_activity_capacity(request.form.get('capacity', '').strip()),
        )
        doc = request.files.get('document')
        saved_rel = None
        if doc and doc.filename:
            ok, message = validate_drive_filename(doc.filename)
            if not ok:
                flash(message, 'danger')
                return redirect(url_for('activities.admin_activity_create', res_id=res_id))
            # 流式落盘 + 单文件 20MB 上限（此前 doc.read() 全量读入内存
            # 且无大小限制，大文件并发上传可撑爆内存/磁盘）
            from app.utils import save_stream_to_disk as _save_stream
            ok_save, msg, rel_path, _size = _save_stream(
                doc, f'activity_docs/{res_id}', doc.filename,
                max_bytes=20 * 1024 * 1024)
            if not ok_save:
                flash(msg or '活动文档保存失败', 'danger')
                return redirect(url_for('activities.admin_activity_create', res_id=res_id))
            saved_rel = rel_path
            activity.document_path = rel_path
            activity.document_name = doc.filename
        db.session.add(activity)
        try:
            db.session.commit()
        except Exception:
            # 提交失败：活动文档已落盘但记录回滚，回收磁盘孤儿文件
            # （与作业投递同口径，避免只占磁盘、无记录引用的残留）
            db.session.rollback()
            _discard_orphan(saved_rel)
            current_app.logger.error('学习活动创建失败', exc_info=True)
            flash('学习活动创建失败，请稍后重试', 'danger')
            return redirect(url_for('activities.admin_activities', res_id=res_id))
        _invalidate_study_cache()
        flash('学习活动已创建', 'success')
        return redirect(url_for('activities.admin_activities', res_id=res_id))
    return render_template('admin_activity_form.html', resource=resource, activity=None)


@activities_bp.route('/admin/activities/<int:act_id>/edit', methods=['GET', 'POST'])
@activities_bp.route('/teacher/activities/<int:act_id>/edit', methods=['GET', 'POST'])
@teacher_login_required
def admin_activity_edit(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not _teacher_can_manage_resource(activity.resource):
        flash('只有资源创建者可以编辑学习活动', 'danger')
        return redirect(url_for('activities.admin_activities',
                                res_id=activity.resource_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('活动名称不能为空', 'danger')
            return redirect(url_for('activities.admin_activity_edit', act_id=act_id))
        old_title = activity.title
        activity.title = title
        activity.description = request.form.get('description', '').strip()
        activity.require_upload = request.form.get('require_upload') == '1'
        activity.sort_order = request.form.get('sort_order', type=int) or 0
        activity.is_active = request.form.get('is_active') == '1'
        activity.start_time = _parse_activity_time(request.form.get('start_time', '').strip())
        activity.end_time = _parse_activity_time(request.form.get('end_time', '').strip())
        activity.capacity = _parse_activity_capacity(request.form.get('capacity', '').strip())
        doc = request.files.get('document')
        old_doc_path = None
        new_doc_path = None
        if doc and doc.filename:
            ok, message = validate_drive_filename(doc.filename)
            if not ok:
                flash(message, 'danger')
                return redirect(url_for('activities.admin_activity_edit', act_id=act_id))
            # 流式落盘 + 单文件 20MB 上限；先保存新文件成功后再删旧文件
            # （此前先删旧后存新，保存失败会丢失原文档）
            from app.utils import save_stream_to_disk as _save_stream
            ok_save, msg, rel_path, _size = _save_stream(
                doc, f'activity_docs/{activity.resource_id}', doc.filename,
                max_bytes=20 * 1024 * 1024)
            if not ok_save:
                flash(msg or '活动文档保存失败', 'danger')
                return redirect(url_for('activities.admin_activity_edit', act_id=act_id))
            # 旧文档路径暂存，延后到 commit 成功后再删：此前在 commit 前删除，
            # 一旦提交失败回滚，document_path 恢复为**已被删除**的旧路径，
            # 活动文档 404，同时新文件成为孤儿
            old_doc_path = activity.document_path
            new_doc_path = rel_path
            activity.document_path = rel_path
            activity.document_name = doc.filename
        if old_title != title:
            _sync_activity_lesson_tree(activity.resource, activity.id,
                                       old_title=old_title, new_title=title)
        try:
            db.session.commit()
        except Exception:
            # 提交失败：回滚并回收刚落盘的新文档（旧文档未动，仍可用）
            db.session.rollback()
            if new_doc_path and new_doc_path != old_doc_path:
                delete_file_from_disk(new_doc_path)
            current_app.logger.warning('活动更新提交失败，已回收新文档', exc_info=True)
            flash('活动更新失败，请重试', 'danger')
            return redirect(url_for('activities.admin_activity_edit', act_id=act_id))
        # 提交成功后再删旧文档（失败仅残留孤儿文件，不影响数据一致性）
        if old_doc_path and old_doc_path != new_doc_path:
            delete_file_from_disk(old_doc_path)
        _invalidate_study_cache()
        flash('学习活动已更新', 'success')
        return redirect(url_for('activities.admin_activities', res_id=activity.resource_id))
    return render_template('admin_activity_form.html', resource=activity.resource, activity=activity)


@activities_bp.route('/admin/activities/<int:act_id>/delete', methods=['POST'])
@activities_bp.route('/teacher/activities/<int:act_id>/delete', methods=['POST'])
@teacher_login_required
def admin_activity_delete(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not _teacher_can_manage_resource(activity.resource):
        flash('只有资源创建者可以删除学习活动', 'danger')
        return redirect(url_for('activities.admin_activities',
                                res_id=activity.resource_id))
    res_id = activity.resource_id
    # 先收集待删磁盘文件，提交成功后再清理：此前先删盘后 commit，提交失败
    # （FK/死锁/连接中断）时记录仍在而文档与全部学生作品已 404，不可恢复
    doc_path = activity.document_path
    work_paths = [w.file_path for w in activity.works if w.file_path]
    _sync_activity_lesson_tree(activity.resource, activity.id, remove=True)
    db.session.delete(activity)
    db.session.commit()
    for rel in ([doc_path] if doc_path else []) + work_paths:
        delete_file_from_disk(rel)
    _invalidate_study_cache()
    flash('学习活动已删除', 'success')
    return redirect(url_for('activities.admin_activities', res_id=res_id))


@activities_bp.route('/study/activity/<int:act_id>', methods=['GET', 'POST'])
@authenticated_required
def student_activity(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not _resource_visible_to_current_user(activity.resource):
        return '无权访问', 403
    student_id = session.get('student_id')
    work = StudentWork.query.filter_by(activity_id=act_id, student_id=student_id).first() if student_id else None
    # 活动关闭：已提交作品的学生仍可查看自己的作品；未提交者不可进入
    if not activity.is_active:
        if request.method == 'POST':
            return '活动已结束', 403
        if not work:
            return '活动已结束', 403
    if request.method == 'POST':
        if not student_id:
            return redirect(url_for('auth.login'))
        if not activity.require_upload:
            flash('该活动不要求提交作品', 'warning')
            return redirect(url_for('activities.student_activity', act_id=act_id))
        # 提交时间窗校验（start_time/end_time 未设置则不限制）
        ok, msg = _activity_accepting(activity)
        if not ok:
            flash(msg, 'danger')
            return redirect(url_for('activities.student_activity', act_id=act_id))
        # 人数上限校验（仅新提交受限；已提交学生重交不受容量影响）
        if not work and activity.capacity:
            # 行锁串行化名额检查（SELECT FOR UPDATE，与小组网盘容量
            # 同款）：count-then-insert 并发提交可小幅超员
            db.session.query(LearningActivity.id).filter_by(
                id=act_id).with_for_update().first()
            submitted_count = StudentWork.query.filter_by(activity_id=act_id).count()
            if submitted_count >= activity.capacity:
                flash(f'该活动提交名额已满（上限 {activity.capacity} 人）', 'danger')
                return redirect(url_for('activities.student_activity', act_id=act_id))
        text_content = request.form.get('text_content', '').strip()
        file = request.files.get('work_file')
        file_path = None
        original_filename = None
        file_size = 0
        if file and file.filename:
            ok, message = validate_drive_filename(file.filename)
            if not ok:
                flash(message, 'danger')
                return redirect(url_for('activities.student_activity', act_id=act_id))
            # 大小上限 20MB（与小组网盘一致）：此前无任何限制，
            # 学生可上传超大文件耗尽磁盘/内存。
            max_size = 20 * 1024 * 1024
            if file.content_length is not None and file.content_length > max_size:
                flash('作品文件不能超过 20MB', 'danger')
                return redirect(url_for('activities.student_activity', act_id=act_id))
            # 流式落盘（save 直写磁盘，超限按 getsize 校验并删除）
            from app.utils import save_stream_to_disk
            ok, msg, rel_path, file_size = save_stream_to_disk(
                file, f'student_works/{act_id}/{student_id}', file.filename,
                max_bytes=max_size)
            if not ok:
                flash(msg, 'danger')
                return redirect(url_for('activities.student_activity', act_id=act_id))
            file_path = rel_path
            original_filename = file.filename
        if not text_content and not file_path:
            flash('请填写说明或上传作品文件', 'danger')
            return redirect(url_for('activities.student_activity', act_id=act_id))
        if work:
            # 旧文件路径暂存：提交成功后再删（此前 commit 前删除，提交失败
            # 回滚后 work.file_path 指向已删除文件，下载 404）
            old_work_path = work.file_path if file_path else None
            work.text_content = text_content or work.text_content
            if file_path:
                work.file_path = file_path
                work.original_filename = original_filename
                work.file_size = file_size
            work.status = 'submitted'
            work.submitted_at = datetime.now()
            work.is_excellent = False
            # 保留教师评价记录（重交不删除教师劳动成果）；
            # 新作品是否优秀由教师重新判定
        else:
            old_work_path = None
            work = StudentWork(
                activity_id=act_id,
                student_id=student_id,
                title=activity.title,
                text_content=text_content,
                file_path=file_path,
                original_filename=original_filename,
                file_size=file_size,
            )
            db.session.add(work)
        try:
            db.session.commit()
        except IntegrityError:
            # 并发重复提交兜底（uq_student_work_activity_student 唯一约束）：
            # 此前未捕获 → 500 错误页，且已写盘的作品文件成为孤儿。
            db.session.rollback()
            if file_path:
                try:
                    delete_file_from_disk(file_path)
                except Exception:
                    pass
            flash('提交失败：检测到重复提交，请刷新页面后重试', 'danger')
            return redirect(url_for('activities.student_activity', act_id=act_id))
        except Exception:
            # 其他提交失败（连接中断/磁盘等）：回滚并回收新文件，保留旧作品
            db.session.rollback()
            if file_path and file_path != old_work_path:
                try:
                    delete_file_from_disk(file_path)
                except Exception:
                    pass
            current_app.logger.warning('作品提交失败，已回收新文件', exc_info=True)
            flash('作品提交失败，请重试', 'danger')
            return redirect(url_for('activities.student_activity', act_id=act_id))
        # 提交成功后再删旧作品文件（失败仅残留孤儿文件）
        if old_work_path and old_work_path != file_path:
            delete_file_from_disk(old_work_path)
        flash('作品已提交', 'success')
        return redirect(url_for('activities.student_activity', act_id=act_id))
    return render_template('student_activity.html', activity=activity, work=work)


def _activity_document_window_ok(activity):
    """活动文档读取窗口：停用/未开始/已结束时仅教师/管理员可读。"""
    if session.get('is_admin') or session.get('is_teacher'):
        return True
    if not activity.is_active:
        return False
    now = datetime.now()
    if activity.start_time and now < activity.start_time:
        return False
    if activity.end_time and now > activity.end_time:
        return False
    return True


@activities_bp.route('/activity/document/<int:act_id>')
@authenticated_required
def activity_document(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not activity.document_path or not _resource_visible_to_current_user(activity.resource):
        return '无权访问', 403
    if not _activity_document_window_ok(activity):
        return '活动已结束', 403
    # 磁盘直送 + conditional（此前全读内存 + BytesIO 中转）
    from app.utils import get_existing_absolute_path
    abs_path = get_existing_absolute_path(activity.document_path)
    if not abs_path:
        return '文件不存在', 404
    filename = activity.document_name or 'activity_document'
    inline = request.args.get('inline') == '1'
    resp = send_large_download(
        abs_path, conditional=True, download_name=filename,
        as_attachment=not inline,
        mimetype=safe_inline_mimetype(filename) if inline else None)
    if inline:
        # Chromium 对 inline + 非文本类型的 fetch 只回 204/空 body，
        # 预览器会拿到 0 字节（见 utils.strip_inline_content_disposition）
        strip_inline_content_disposition(resp)
    return resp


@activities_bp.route('/activity/document/<int:act_id>/preview')
@authenticated_required
def activity_document_preview(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not activity.document_path or not _resource_visible_to_current_user(activity.resource):
        return '无权访问', 403
    if not _activity_document_window_ok(activity):
        return '活动已结束', 403
    file_url = url_for('activities.activity_document', act_id=act_id, inline=1)
    # 返回路径按来源区分：教师从「学习活动」列表预览时返回活动管理页，
    # 学生（或默认）返回学生活动页；学生伪造 source 不会拿到教师页面。
    source = (request.args.get('source') or '').strip()
    back_url = url_for('activities.student_activity', act_id=act_id)
    back_label = '返回活动'
    if source == 'activities' and (session.get('is_admin')
                                   or session.get('is_teacher')):
        back_url = url_for('activities.admin_activities',
                           res_id=activity.resource_id)
        back_label = '返回学习活动'
    return render_template('document_preview.html',
                           filename=activity.document_name or '活动文档',
                           file_url=file_url,
                           download_url=url_for('activities.activity_document', act_id=act_id),
                           media_type=get_preview_type(activity.document_name or ''),
                           back_url=back_url, back_label=back_label)


@activities_bp.route('/works/file/<int:work_id>')
@authenticated_required
def work_file(work_id):
    work = db.get_or_404(StudentWork, work_id)
    if not _can_access_work(work) or not work.file_path:
        return '无权访问', 403
    # 教师查看作品文件同样受课堂资源可见性与当前上课班级边界约束
    if session.get('is_teacher') and (
            not _teacher_resource_visible(work.activity.resource) or
            not _teacher_can_grade_work(work)):
        return '无权访问', 403
    # 磁盘直送 + conditional（此前全读内存 + BytesIO 中转）
    from app.utils import get_existing_absolute_path
    abs_path = get_existing_absolute_path(work.file_path)
    if not abs_path:
        return '文件不存在', 404
    filename = work.original_filename or 'work'
    inline = request.args.get('inline') == '1'
    resp = send_large_download(
        abs_path, conditional=True, download_name=filename,
        as_attachment=not inline,
        mimetype=safe_inline_mimetype(filename) if inline else None)
    if inline:
        # Chromium 对 inline + 非文本类型的 fetch 只回 204/空 body，
        # 预览器会拿到 0 字节（见 utils.strip_inline_content_disposition）
        strip_inline_content_disposition(resp)
    return resp


@activities_bp.route('/works/file/<int:work_id>/preview')
@authenticated_required
def work_file_preview(work_id):
    work = db.get_or_404(StudentWork, work_id)
    if not _can_access_work(work):
        return '无权访问', 403
    # 教师预览作品文件同样受课堂资源可见性与当前上课班级边界约束
    if session.get('is_teacher') and (
            not _teacher_resource_visible(work.activity.resource) or
            not _teacher_can_grade_work(work)):
        return '无权访问', 403
    file_url = url_for('activities.work_file', work_id=work_id, inline=1)
    # 预览页来源决定“返回”去向：作品列表 / 评价页 / 学生活动页。
    # 用显式 source 参数而不是 referrer：新标签页可能被隐私策略去掉 Referer。
    source = (request.args.get('source') or '').strip()
    back_url = url_for('activities.student_activity', act_id=work.activity_id)
    back_label = '返回活动'
    if session.get('is_admin') or session.get('is_teacher'):
        if source == 'works':
            back_kwargs = {'act_id': work.activity_id}
            page = request.args.get('page', type=int)
            if page and page > 0:
                back_kwargs['page'] = page
            back_url = url_for('activities.admin_works_activity', **back_kwargs)
            back_label = '返回作品列表'
        elif source == 'evaluate':
            back_url = url_for('activities.admin_work_evaluate', work_id=work_id)
            back_label = '返回评价页'
    return render_template('document_preview.html',
                           filename=work.original_filename or '作品文件',
                           file_url=file_url,
                           download_url=url_for('activities.work_file', work_id=work_id),
                           media_type=get_preview_type(work.original_filename or ''),
                           back_url=back_url,
                           back_label=back_label)


@activities_bp.route('/admin/works')
@activities_bp.route('/teacher/works')
@teacher_login_required
def admin_works():
    from app.utils import paginate_query
    query = LearningActivity.query.options(joinedload(LearningActivity.resource))
    if not session.get('is_admin'):
        mode = session.get('teacher_mode') or 'edit'
        visible_ids = teacher_visible_resources(
            session.get('teacher_id'), is_admin=False,
            mode=mode, classroom=(mode != 'edit')
        ).with_entities(Resource.id)
        query = query.filter(LearningActivity.resource_id.in_(visible_ids))
    pagination = paginate_query(
        query.order_by(LearningActivity.created_at.desc()),
        default_per_page=20, max_per_page=100
    )
    activities = pagination.items
    stats = {}
    if activities:
        stats_query = db.session.query(
            StudentWork.activity_id,
            func.count(StudentWork.id),
            func.sum(case((StudentWork.is_excellent.is_(True), 1), else_=0))
        ).filter(StudentWork.activity_id.in_([a.id for a in activities]))
        if not session.get('is_admin'):
            # 作品云盘统计与详情列表使用同一教师班级边界，避免教师从
            # “N 件作品”汇总数字推断其他班级的提交量。
            class_ids = teacher_class_ids(session.get('teacher_id'))
            if class_ids:
                stats_query = stats_query.join(
                    Student, Student.id == StudentWork.student_id
                ).filter(Student.class_id.in_(class_ids))
            else:
                stats_query = stats_query.filter(db.false())
        rows = stats_query.group_by(StudentWork.activity_id).all()
        stats = {row[0]: {'count': row[1], 'excellent': row[2] or 0} for row in rows}
    return render_template('admin_works.html', activities=activities, stats=stats,
                           pagination=pagination)


@activities_bp.route('/admin/works/activity/<int:act_id>')
@activities_bp.route('/teacher/works/activity/<int:act_id>')
@teacher_login_required
def admin_works_activity(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not _teacher_resource_visible(activity.resource):
        flash('该资源不在教师课堂端展示', 'danger')
        return redirect(url_for('activities.admin_works'))
    # 教师数据边界：非管理员仅可查看当前上课班级学生的作品列表
    # （此前仅按活动过滤，可横向查看其他班级学生的姓名/作品/得分）
    # joinedload：模板循环访问 work.student.name，消除每行 1 次额外 SQL
    # joinedload(evaluation)：模板每行访问 work.evaluation，修前每行 1 次
    # SELECT。work.student.class_ 无需预取——视图下方 Class.query.all() 已把
    # 全部班级装进 identity map，many-to-one 懒加载走 use_get 直接命中，不发
    # SQL（实测；同理 admin_student_drive 的 s.class_ 也不是真 N+1）
    query = StudentWork.query.options(
        joinedload(StudentWork.student),
        joinedload(StudentWork.evaluation)).filter_by(activity_id=act_id)
    if session.get('is_teacher') and not session.get('is_admin'):
        class_ids = teacher_class_ids(session.get('teacher_id'))
        if class_ids:
            query = query.join(Student, Student.id == StudentWork.student_id).filter(
                Student.class_id.in_(class_ids))
        else:
            query = query.filter(db.false())
    from app.utils import paginate_query
    pagination = paginate_query(
        query.order_by(StudentWork.submitted_at.desc()),
        default_per_page=20, max_per_page=100
    )
    works = pagination.items
    threshold = ExcellenceThreshold.query.filter_by(activity_id=act_id).first()
    classes = Class.query.order_by(Class.name).all()
    can_manage = _teacher_can_manage_resource(activity.resource)
    return render_template('admin_works_activity.html',
                           activity=activity, works=works, threshold=threshold, classes=classes,
                           can_manage=can_manage, pagination=pagination)


@activities_bp.route('/admin/works/<int:work_id>/delete', methods=['POST'])
@activities_bp.route('/teacher/works/<int:work_id>/delete', methods=['POST'])
@teacher_login_required
def admin_work_delete(work_id):
    """删除学生作品（资源创建者或管理员）。

    删除后学生端该活动恢复为“未提交”状态（可重新上传）。作品评价随
    作品级联删除；磁盘文件在 DB 提交成功后清理（失败仅残留孤儿文件，
    不会出现“记录在、文件无”的悬空状态）。
    """
    work = db.get_or_404(StudentWork, work_id)
    if not _teacher_can_manage_resource(work.activity.resource):
        abort(403)
    act_id = work.activity_id
    student_name = work.student.name if work.student else '学生已删除'
    rel_path = work.file_path
    db.session.add(Log(
        user_id=0, user_type='admin' if session.get('is_admin') else 'teacher',
        action='删除学生作品',
        detail=(f'活动ID: {act_id}, 学生: {student_name}, '
                f'文件: {work.original_filename or "无"}'),
        time=datetime.now()))
    db.session.delete(work)  # WorkEvaluation 由关系级联删除
    db.session.commit()
    if rel_path:
        try:
            delete_file_from_disk(rel_path)
        except Exception:
            current_app.logger.warning(
                '删除学生作品磁盘文件失败（忽略，仅残留孤儿文件）: %s',
                rel_path, exc_info=True)
    flash('已删除该学生作品；学生端将恢复为未提交状态', 'success')
    return redirect(url_for('activities.admin_works_activity', act_id=act_id))


@activities_bp.route('/admin/works/evaluate/<int:work_id>', methods=['GET', 'POST'])
@activities_bp.route('/teacher/works/evaluate/<int:work_id>', methods=['GET', 'POST'])
@teacher_login_required
def admin_work_evaluate(work_id):
    work = db.get_or_404(StudentWork, work_id)
    if not _teacher_resource_visible(work.activity.resource):
        flash('该资源不在教师课堂端展示', 'danger')
        return redirect(url_for('activities.admin_works'))
    # 教师数据边界：仅能批改当前上课班级学生的作品
    if not _teacher_can_grade_work(work):
        flash('仅能批改当前上课班级学生的作品', 'danger')
        return redirect(url_for('activities.admin_works'))
    if request.method == 'POST':
        score_raw = request.form.get('score', '').strip()
        try:
            score = float(score_raw) if score_raw != '' else None
        except ValueError:
            flash('分数格式无效', 'danger')
            return redirect(url_for('activities.admin_works_activity', act_id=work.activity_id))
        # 校验分数范围，防止负分或异常大值
        if score is not None and (math.isnan(score) or math.isinf(score) or score < 0 or score > 1000):
            flash('分数应在 0-1000 之间', 'danger')
            return redirect(url_for('activities.admin_works_activity', act_id=work.activity_id))
        evaluation = work.evaluation or WorkEvaluation(work_id=work.id)
        evaluation.score = score
        evaluation.grade = request.form.get('grade', '').strip()
        evaluation.comment = request.form.get('comment', '').strip()
        evaluation.evaluated_by = _teacher_name()
        evaluation.evaluated_at = datetime.now()
        if not work.evaluation:
            db.session.add(evaluation)
            work.evaluation = evaluation
        work.status = 'evaluated'
        _apply_excellence_rule(work)
        db.session.commit()
        flash('作品评价已保存', 'success')
        return redirect(url_for('activities.admin_works_activity', act_id=work.activity_id))
    return render_template('admin_work_evaluate.html', work=work)


@activities_bp.route('/admin/works/threshold/<int:act_id>', methods=['POST'])
@activities_bp.route('/teacher/works/threshold/<int:act_id>', methods=['POST'])
@teacher_login_required
def admin_work_threshold(act_id):
    activity = db.get_or_404(LearningActivity, act_id)
    if not _teacher_resource_visible(activity.resource):
        flash('该资源不在教师课堂端展示', 'danger')
        return redirect(url_for('activities.admin_works'))
    threshold = ExcellenceThreshold.query.filter_by(activity_id=act_id).first()
    if not threshold:
        threshold = ExcellenceThreshold(activity_id=act_id)
        db.session.add(threshold)
    # 显式处理 min_score：request.form.get(..., type=float) 在输入 "nan"/"inf" 时
    # 会返回 NaN/Infinity（均为 truthy），原写法 `... or 90` 无法拦截，导致阈值失效。
    raw_min_score = request.form.get('min_score', type=float)
    if raw_min_score is None or math.isnan(raw_min_score) or math.isinf(raw_min_score):
        threshold.min_score = 90
    else:
        threshold.min_score = raw_min_score
    threshold.grade_levels = request.form.get('grade_levels', '').strip() or 'A+,A'
    for work in StudentWork.query.filter_by(activity_id=act_id).all():
        _apply_excellence_rule(work)
    db.session.commit()
    flash('优秀作品阈值已更新', 'success')
    return redirect(url_for('activities.admin_works_activity', act_id=act_id))


@activities_bp.route('/works/excellent')
@authenticated_required
def excellent_works():
    from app.utils import paginate_query
    # joinedload：模板循环访问 work.student.name / work.activity.title /
    # work.evaluation（评价是 uselist=False 反查，不预加载则每行各查一次）
    pagination = paginate_query(
        StudentWork.query.options(
            joinedload(StudentWork.student),
            joinedload(StudentWork.activity),
            joinedload(StudentWork.evaluation)
        ).filter_by(is_excellent=True).order_by(
            StudentWork.submitted_at.desc()),
        default_per_page=20, max_per_page=100
    )
    return render_template('excellent_works.html', works=pagination.items,
                           pagination=pagination)


@activities_bp.route('/works/public/<token>')
def public_work(token):
    work = StudentWork.query.filter_by(public_token=token, is_excellent=True).first_or_404()
    return render_template('public_work.html', work=work)


@activities_bp.route('/works/public/<token>/file')
def public_work_file(token):
    work = StudentWork.query.filter_by(public_token=token, is_excellent=True).first_or_404()
    if not work.file_path:
        return '文件不存在', 404
    # 磁盘直送 + conditional（此前全读内存 + BytesIO 中转）
    from app.utils import get_existing_absolute_path
    abs_path = get_existing_absolute_path(work.file_path)
    if not abs_path:
        return '文件不存在', 404
    filename = work.original_filename or 'work'
    inline = request.args.get('inline') == '1'
    resp = send_large_download(
        abs_path, conditional=True, download_name=filename,
        as_attachment=not inline,
        mimetype=safe_inline_mimetype(filename) if inline else None)
    if inline:
        # Chromium 对 inline + 非文本类型的 fetch 只回 204/空 body，
        # 预览器会拿到 0 字节（见 utils.strip_inline_content_disposition）
        strip_inline_content_disposition(resp)
    return resp


@activities_bp.route('/works/public/<token>/preview')
def public_work_preview(token):
    work = StudentWork.query.filter_by(public_token=token, is_excellent=True).first_or_404()
    file_url = url_for('activities.public_work_file', token=token, inline=1)
    return render_template('document_preview.html',
                           filename=work.original_filename or '作品文件',
                           file_url=file_url,
                           download_url=url_for('activities.public_work_file', token=token),
                           media_type=get_preview_type(work.original_filename or ''),
                           back_url=url_for('activities.public_work', token=token))
