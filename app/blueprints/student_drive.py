
from flask import (Blueprint, request, render_template, redirect, url_for,
                   session, flash, jsonify)
from sqlalchemy import false, func, or_

from app.extensions import db
from app.models import Class, Student, StudentDriveFile
from app.decorators import (login_required, admin_login_required,
                            teacher_login_required, authenticated_required)
from app.services.resource_access import teacher_class_ids
from app.services.download_pool import send_large_download
from app.services.student_drive_service import (
    save_drive_file_for_student, delete_drive_file,
    get_student_drive_used, get_student_drive_quota, get_preview_type,
    MAX_DRIVE_FILE_SIZE_MB, DEFAULT_STUDENT_DRIVE_QUOTA_MB, _discard_orphan,
)
from app.utils import safe_inline_mimetype, parse_int, strip_inline_content_disposition


student_drive_bp = Blueprint('student_drive', __name__, url_prefix='')


def _current_sender():
    if session.get('is_admin'):
        return 'admin', None, '管理员'
    return 'teacher', session.get('teacher_id'), session.get('teacher_name') or '教师'


def _teacher_can_access_student(student):
    """教师数据边界：仅当前上课班级（active_class_id）的学生；管理员全部放行"""
    if session.get('is_admin'):
        return True
    class_ids = teacher_class_ids(session.get('teacher_id'))
    return bool(student and student.class_id in class_ids)


def _can_access_file(record):
    if session.get('is_admin'):
        return True
    if session.get('is_teacher'):
        # 教师仅能查看当前上课班级学生的网盘文件
        return _teacher_can_access_student(record.student)
    return bool(session.get('student_id') and session.get('student_id') == record.student_id)


@student_drive_bp.route('/student/drive')
@login_required
def student_drive():
    student_id = session.get('student_id')
    student = db.get_or_404(Student, student_id)
    # 个人网盘文件分页（文件会长期累积）
    from app.utils import paginate_query
    pagination = paginate_query(
        StudentDriveFile.query.filter_by(student_id=student_id).order_by(
            StudentDriveFile.created_at.desc()),
        default_per_page=20, max_per_page=100
    )
    files = pagination.items
    used = get_student_drive_used(student_id)
    quota = get_student_drive_quota(student_id)
    return render_template('student_drive.html',
                           student=student, files=files, used=used, quota=quota,
                           max_file_size_mb=MAX_DRIVE_FILE_SIZE_MB,
                           quota_mb=DEFAULT_STUDENT_DRIVE_QUOTA_MB,
                           pagination=pagination)


@student_drive_bp.route('/student/drive/upload', methods=['POST'])
@login_required
def student_drive_upload():
    student_id = session.get('student_id')
    student = db.get_or_404(Student, student_id)
    file = request.files.get('file')
    if not file or not file.filename:
        flash('请选择文件', 'danger')
        return redirect(url_for('student_drive.student_drive'))
    try:
        # 流式落盘（file_storage.save 直写磁盘，不整文件读入内存；
        # 大小/魔数/配额校验在 service 层完成）
        save_drive_file_for_student(
            student_id,
            None,
            file.filename,
            sender_type='student',
            sender_id=student_id,
            sender_name=student.name,
            source_type='student_upload',
            note='学生自行上传',
            commit=True,
            file_storage=file
        )
        flash('文件已上传到个人网盘', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('student_drive.student_drive'))


@student_drive_bp.route('/student/drive/download/<int:file_id>')
@authenticated_required
def student_drive_download(file_id):
    record = db.get_or_404(StudentDriveFile, file_id)
    if not _can_access_file(record):
        return '无权访问', 403
    # 磁盘直送 + conditional=True（此前全读内存 + BytesIO 中转，
    # 200MB 文件单请求内存峰值 ≥200MB；直送获得 Range/304 断点续传）
    from app.utils import get_existing_absolute_path
    abs_path = get_existing_absolute_path(record.file_path)
    if not abs_path:
        return '文件不存在', 404
    inline = request.args.get('inline') == '1'
    mimetype = safe_inline_mimetype(record.original_filename) if inline else None
    resp = send_large_download(abs_path, conditional=True,
                               download_name=record.original_filename,
                               as_attachment=not inline, mimetype=mimetype)
    if inline:
        # 去掉 CD 头：Chromium 对 inline + 非文本类型的 fetch 只回 204/空
        # body（实测矩阵见 utils.strip_inline_content_disposition）。
        # 此前把同一现象归因于「启发式缓存 × Range 交互」并加 no-store
        # 处理，实测无效——真正致因是 CD 头。no-store 保留，仅为私有
        # 动态内容禁缓存。
        strip_inline_content_disposition(resp)
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@student_drive_bp.route('/student/drive/preview/<int:file_id>')
@authenticated_required
def student_drive_preview(file_id):
    record = db.get_or_404(StudentDriveFile, file_id)
    if not _can_access_file(record):
        return '无权访问', 403
    filename = record.original_filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    back_url = url_for('student_drive.student_drive')
    if session.get('is_admin') or session.get('is_teacher'):
        back_url = url_for('student_drive.admin_student_drive_detail',
                           student_id=record.student_id)

    # PPTX/PPT → PPTist 嵌入预览（懒解析；与小组网盘同构）
    if ext in ('pptx', 'ppt'):
        json_url = url_for('student_drive.drive_json', file_id=file_id)
        save_json_url = url_for('student_drive.drive_save_json', file_id=file_id)
        download_url = url_for('student_drive.student_drive_download',
                               file_id=file_id, inline=1)
        return render_template('pptist_embed.html',
                               submode='preview',
                               filename=filename,
                               file_id=file_id,
                               json_url=json_url,
                               save_json_url=save_json_url,
                               download_url=download_url,
                               back_url=back_url)

    file_url = url_for('student_drive.student_drive_download', file_id=file_id,
                       inline=1)
    download_url = url_for('student_drive.student_drive_download', file_id=file_id)
    return render_template('document_preview.html',
                           filename=filename,
                           file_url=file_url,
                           download_url=download_url,
                           media_type=get_preview_type(filename),
                           back_url=back_url)


@student_drive_bp.route('/student/drive/json/<int:file_id>')
@authenticated_required
def drive_json(file_id):
    """个人网盘 PPTist JSON 数据（带版本校验；404 触发浏览器重新解析）。
    教师/管理员经 _can_access_file 放行只读（预览页快路径），保存仍限本人"""
    import json as _json
    from app.blueprints.student_groups import PPTIST_DATA_VERSION
    record = db.get_or_404(StudentDriveFile, file_id)
    if not _can_access_file(record):
        return jsonify({'error': '无权访问'}), 403
    if not record.pptist_json:
        return jsonify({'error': '该文件没有预生成的 JSON 数据'}), 404
    try:
        data = _json.loads(record.pptist_json)
    except (ValueError, TypeError):
        return jsonify({'error': 'JSON 数据损坏'}), 500
    if data.get('_v') != PPTIST_DATA_VERSION:
        return jsonify({'error': 'PPTist 数据版本过旧'}), 404
    from flask import Response
    return Response(record.pptist_json, mimetype='application/json')


@student_drive_bp.route('/student/drive/save-json/<int:file_id>', methods=['POST'])
@login_required
def drive_save_json(file_id):
    """保存个人网盘 PPTist JSON（结构校验 + XSS 净化 + 版本标记 + 大小限制；
    仅文件归属学生可保存，教师/管理员预览只读）"""
    import json as _json
    from app.blueprints.student_groups import PPTIST_DATA_VERSION, _sanitize_pptist_json
    student_id = session.get('student_id')
    record = db.get_or_404(StudentDriveFile, file_id)
    if not student_id or record.student_id != student_id:
        return jsonify({'error': '无权访问'}), 403
    # 只有 PPT 才有 PPTist 数据：否则可给任意 1 字节文件挂 20MB JSON，
    # 且这部分不计配额 → 反复操作即可无限撑大数据库
    if (record.original_filename or '').rsplit('.', 1)[-1].lower() not in ('ppt', 'pptx'):
        return jsonify({'error': '仅 PPT 文件支持保存课件数据'}), 400
    data = request.get_json(silent=True)
    # 仅接受 JSON 对象（PPTist 导出格式；顶层 list 读回时 data.get 会 500）
    if not isinstance(data, dict):
        return jsonify({'error': '无效的 JSON 数据'}), 400
    if isinstance(data, dict) and 'slides' in data:
        slides = data['slides']
        if not isinstance(slides, list) or not all(isinstance(s, dict) for s in slides):
            return jsonify({'error': 'PPTist 数据结构无效'}), 400
    try:
        data = _sanitize_pptist_json(data)
    except ValueError:
        return jsonify({'error': '包含危险 HTML 内容'}), 400
    if isinstance(data, dict):
        data['_v'] = PPTIST_DATA_VERSION
    json_str = _json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # 与课堂课件缓存端点同口径 20MB（全局 JSON 请求上限 25MB 在其之上）
    new_len = len(json_str.encode('utf-8'))
    if new_len > 20 * 1024 * 1024:
        return jsonify({'error': 'PPTist 数据超过 20MB 限制'}), 413
    # 课件数据计入网盘配额（文件体积 + 其余文件的课件数据 + 本次数据）
    from sqlalchemy import func as _func
    from app.services.student_drive_service import (get_student_drive_used,
                                                    get_student_drive_quota)
    other_json = db.session.query(_func.coalesce(_func.sum(
        _func.octet_length(StudentDriveFile.pptist_json)), 0)).filter(
        StudentDriveFile.student_id == student_id,
        StudentDriveFile.id != record.id).scalar() or 0
    if get_student_drive_used(student_id) + other_json + new_len > \
            get_student_drive_quota(student_id):
        return jsonify({'error': '网盘空间不足，无法保存课件数据'}), 413
    record.pptist_json = json_str
    db.session.commit()
    return jsonify({'ok': True})


@student_drive_bp.route('/student/drive/edit/<int:file_id>')
@login_required
def drive_edit(file_id):
    """编辑个人网盘 PPTX — PPTist iframe 嵌入（仅文件归属学生）"""
    student_id = session.get('student_id')
    record = db.get_or_404(StudentDriveFile, file_id)
    if not student_id or record.student_id != student_id:
        return '无权访问', 403

    filename = record.original_filename
    json_url = url_for('student_drive.drive_json', file_id=file_id)
    save_json_url = url_for('student_drive.drive_save_json', file_id=file_id)
    download_url = url_for('student_drive.student_drive_download',
                           file_id=file_id, inline=1)
    return render_template('pptist_embed.html',
                           submode='editor',
                           filename=filename,
                           file_id=file_id,
                           json_url=json_url,
                           save_json_url=save_json_url,
                           download_url=download_url,
                           back_url=url_for('student_drive.student_drive'))


@student_drive_bp.route('/student/drive/delete/<int:file_id>', methods=['POST'])
@authenticated_required
def student_drive_delete(file_id):
    record = db.get_or_404(StudentDriveFile, file_id)
    if not _can_access_file(record):
        return '无权操作', 403
    student_id = record.student_id
    admin_side = bool(session.get('is_admin') or session.get('is_teacher'))
    try:
        delete_drive_file(record, commit=True)
        flash('文件已删除', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'删除失败: {exc}', 'danger')
    if admin_side:
        return redirect(url_for('student_drive.admin_student_drive_detail', student_id=student_id))
    return redirect(url_for('student_drive.student_drive'))


@student_drive_bp.route('/admin/student-drive')
@student_drive_bp.route('/teacher/student-drive')
@teacher_login_required
def admin_student_drive():
    class_id = request.args.get('class_id', type=int)
    keyword = request.args.get('q', '').strip()

    query = Student.query
    if not session.get('is_admin'):
        # 教师数据边界：学生网盘列表仅显示本人任课班级的学生；
        # 未分配班级时不显示任何学生，fail-closed
        class_ids = teacher_class_ids(session.get('teacher_id'))
        query = query.filter(Student.class_id.in_(class_ids)) if class_ids \
            else query.filter(false())
    if class_id:
        query = query.filter(Student.class_id == class_id)
    if keyword:
        like = f'%{keyword}%'
        query = query.filter(or_(Student.name.ilike(like), Student.student_number.ilike(like)))
    # 分页渲染（学生数千人时避免单页全量加载）
    from app.utils import paginate_query
    pagination = paginate_query(
        query.order_by(Student.class_id, Student.student_number, Student.name),
        default_per_page=20, max_per_page=100
    )
    students = pagination.items

    student_ids = [s.id for s in students]
    stats = {}
    if student_ids:
        rows = db.session.query(
            StudentDriveFile.student_id,
            func.count(StudentDriveFile.id),
            func.coalesce(func.sum(StudentDriveFile.file_size), 0)
        ).filter(StudentDriveFile.student_id.in_(student_ids)).group_by(
            StudentDriveFile.student_id).all()
        stats = {row[0]: {'count': row[1], 'size': row[2]} for row in rows}

    classes = Class.query.order_by(Class.name).all()

    # 批量加载容量覆盖（当前页学生的覆盖 + 其班级覆盖 + 全局默认）
    from app.models import StudentDriveQuota, SystemConfig
    page_sids = [s.id for s in students]
    stu_quotas = {}
    cls_quotas = {}
    if page_sids:
        for q in StudentDriveQuota.query.filter(
                StudentDriveQuota.student_id.in_(page_sids)).all():
            stu_quotas[q.student_id] = q.quota_mb
    page_cids = {s.class_id for s in students if s.class_id}
    if page_cids:
        for q in StudentDriveQuota.query.filter(
                StudentDriveQuota.class_id.in_(page_cids)).all():
            cls_quotas[q.class_id] = q.quota_mb
    try:
        # 回退值与服务层 get_student_drive_quota 保持同源：此前这里回退
        # 1024MB 而实际执行 20MB（DEFAULT_STUDENT_DRIVE_QUOTA_MB），配置行
        # 缺失时管理页显示的默认配额与学生真实可用空间不一致
        default_mb = int(SystemConfig.get(
            'drive_default_quota_mb', str(DEFAULT_STUDENT_DRIVE_QUOTA_MB))
            or DEFAULT_STUDENT_DRIVE_QUOTA_MB)
    except (TypeError, ValueError):
        default_mb = DEFAULT_STUDENT_DRIVE_QUOTA_MB
    # 每个学生的实际配额与覆盖来源（用于界面展示）
    quota_map = {}
    for s in students:
        if s.id in stu_quotas:
            quota_map[s.id] = {'mb': stu_quotas[s.id], 'source': 'student'}
        elif s.class_id in cls_quotas:
            quota_map[s.id] = {'mb': cls_quotas[s.class_id], 'source': 'class'}
        else:
            quota_map[s.id] = {'mb': default_mb, 'source': 'default'}

    from app.services.student_drive_service import get_cleanup_config
    cleanup_config = get_cleanup_config()
    return render_template('admin_student_drive.html',
                           students=students, stats=stats, classes=classes,
                           class_id=class_id, keyword=keyword,
                           quota_mb=DEFAULT_STUDENT_DRIVE_QUOTA_MB,
                           pagination=pagination, quota_map=quota_map,
                           default_quota_mb=default_mb,
                           cleanup_config=cleanup_config)


# ── 网盘批量管理 API（容量设置 / 自动清理）──

@student_drive_bp.route('/admin/student-drive/quota/global', methods=['POST'])
@admin_login_required
def quota_set_global():
    """设置全局默认网盘容量（MB）"""
    from app.services.student_drive_service import set_drive_quota_mb
    try:
        quota_mb = parse_int(request.form.get('quota_mb'))
        set_drive_quota_mb(None, quota_mb, target_type='global')
        return jsonify({'success': True, 'message': f'全局默认容量已设置为 {quota_mb} MB'})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@student_drive_bp.route('/admin/student-drive/quota/class', methods=['POST'])
@admin_login_required
def quota_set_class():
    """按班级批量设置网盘容量（覆盖该班全体学生）"""
    from app.services.student_drive_service import set_drive_quota_mb
    class_id = parse_int(request.form.get('class_id'))
    quota_mb = parse_int(request.form.get('quota_mb'))
    if not class_id:
        return jsonify({'success': False, 'message': '请选择班级'}), 400
    cls = db.session.get(Class, class_id)
    if not cls:
        return jsonify({'success': False, 'message': '班级不存在'}), 404
    try:
        set_drive_quota_mb(class_id, quota_mb, target_type='class')
        return jsonify({'success': True,
                        'message': f'已设置 {cls.name} 班网盘容量为 {quota_mb} MB'})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@student_drive_bp.route('/admin/student-drive/quota/students', methods=['POST'])
@admin_login_required
def quota_set_students():
    """批量设置选定学生的网盘容量（勾选学生）"""
    from app.services.student_drive_service import set_drive_quota_mb_bulk
    ids_raw = request.form.get('student_ids', '')
    quota_mb = parse_int(request.form.get('quota_mb'))
    ids = [int(i) for i in ids_raw.split(',') if i.strip().isdigit()]
    if not ids:
        return jsonify({'success': False, 'message': '请选择学生'}), 400
    try:
        # 批量：单次 IN 查询 + 单次提交（此前逐生一次 SELECT+COMMIT，
        # 勾选整年级时数千次数据库往返全部压在请求线程上）
        n = set_drive_quota_mb_bulk(ids, quota_mb)
        return jsonify({'success': True,
                        'message': f'已为 {n} 名学生设置容量 {quota_mb} MB'})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@student_drive_bp.route('/admin/student-drive/quota/clear', methods=['POST'])
@admin_login_required
def quota_clear():
    """清除容量覆盖（恢复全局默认）"""
    from app.services.student_drive_service import clear_drive_quota_override
    target_type = request.form.get('target_type', '')
    target = parse_int(request.form.get('target_id'))
    if not target:
        return jsonify({'success': False, 'message': '参数缺失'}), 400
    try:
        clear_drive_quota_override(target, target_type=target_type)
        return jsonify({'success': True, 'message': '已恢复默认容量'})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@student_drive_bp.route('/admin/student-drive/cleanup-config', methods=['POST'])
@admin_login_required
def cleanup_config_save():
    """保存网盘自动清理配置"""
    from app.services.student_drive_service import set_cleanup_config
    enabled = request.form.get('enabled') == 'on'
    try:
        cfg = set_cleanup_config(
            enabled,
            parse_int(request.form.get('idle_days'), 90) or 90,
            parse_int(request.form.get('interval_hours'), 24) or 24,
        )
        return jsonify({'success': True, 'message': '自动清理配置已保存', 'data': cfg})
    except (ValueError, TypeError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@student_drive_bp.route('/admin/student-drive/cleanup-preview')
@admin_login_required
def cleanup_preview():
    """待清理闲置文件清单（不执行删除）"""
    from app.services.student_drive_service import find_idle_drive_files, get_cleanup_config
    cfg = get_cleanup_config()
    rows = find_idle_drive_files(cfg['idle_days'])
    total_mb = sum((r.file_size or 0) for r, _ in rows) // (1024 * 1024)
    preview = [{
        'student': s.name if s else '未知',
        'class': s.student_class if s else '',
        'filename': r.filename,
        'size_mb': round((r.file_size or 0) / (1024 * 1024), 2),
        'upload_time': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
    } for r, s in rows[:15]]
    return jsonify({'success': True, 'data': {
        'total': len(rows), 'total_mb': total_mb,
        'idle_days': cfg['idle_days'], 'preview': preview,
    }})


@student_drive_bp.route('/admin/student-drive/cleanup-run', methods=['POST'])
@admin_login_required
def cleanup_run():
    """立即执行一次闲置文件清理"""
    from app.services.student_drive_service import get_cleanup_config, cleanup_idle_drive_files
    cfg = get_cleanup_config()
    result = cleanup_idle_drive_files(cfg['idle_days'], log_action='手动清理闲置网盘文件')
    return jsonify({
        'success': True,
        'message': (f"已清理 {result['deleted']} 个闲置文件"
                    f"（释放 {result['freed_mb']}MB）"
                    + (f"，{result['failed']} 个失败" if result['failed'] else '')),
        'data': result,
    })


@student_drive_bp.route('/admin/student-drive/<int:student_id>')
@student_drive_bp.route('/teacher/student-drive/<int:student_id>')
@teacher_login_required
def admin_student_drive_detail(student_id):
    student = db.get_or_404(Student, student_id)
    if not _teacher_can_access_student(student):
        flash('仅能查看当前上课班级学生的网盘', 'danger')
        return redirect(url_for('student_drive.admin_student_drive'))
    files = StudentDriveFile.query.filter_by(student_id=student_id).order_by(
        StudentDriveFile.created_at.desc()).all()
    used = get_student_drive_used(student_id)
    quota = get_student_drive_quota(student_id)
    return render_template('admin_student_drive_detail.html',
                           student=student, files=files, used=used, quota=quota,
                           max_file_size_mb=MAX_DRIVE_FILE_SIZE_MB,
                           quota_mb=DEFAULT_STUDENT_DRIVE_QUOTA_MB)


@student_drive_bp.route('/admin/student-drive/<int:student_id>/send', methods=['POST'])
@student_drive_bp.route('/teacher/student-drive/<int:student_id>/send', methods=['POST'])
@teacher_login_required
def admin_student_drive_send(student_id):
    student = db.get_or_404(Student, student_id)
    if not _teacher_can_access_student(student):
        flash('仅能向当前上课班级的学生发送文件', 'danger')
        return redirect(url_for('student_drive.admin_student_drive'))
    files = request.files.getlist('files') or request.files.getlist('file')
    note = request.form.get('note', '').strip()
    if not files or not any(f.filename for f in files):
        flash('请选择要发送的文件', 'danger')
        return redirect(url_for('student_drive.admin_student_drive_detail', student_id=student_id))

    sender_type, sender_id, sender_name = _current_sender()
    sent = 0
    errors = []
    for file in files:
        if not file or not file.filename:
            continue
        rel = None
        try:
            # 流式落盘（服务层完成大小/魔数/配额校验，不整文件读入内存）
            rel = save_drive_file_for_student(
                student_id,
                None,
                file.filename,
                sender_type=sender_type,
                sender_id=sender_id,
                sender_name=sender_name,
                source_type='manual',
                note=note or '教师发送文件',
                commit=False,
                file_storage=file
            )
            # 逐文件提交：此前整批只在循环后 commit 一次，提交失败时已落盘的
            # 文件全部成为无记录引用的磁盘孤儿（只占磁盘、不计配额），且结果
            # 误报成功。改为逐条提交 + 失败回收，与作业投递同一容错语义
            db.session.commit()
            sent += 1
        except ValueError as exc:
            db.session.rollback()
            _discard_orphan(rel)
            errors.append(f'{file.filename}: {exc}')
        except Exception:
            # commit 失败等异常：文件已写而记录回滚，回收磁盘文件
            db.session.rollback()
            _discard_orphan(rel)
            errors.append(f'{file.filename}: 保存失败')
    if sent:
        flash(f'已发送 {sent} 个文件到学生网盘', 'success')
    for err in errors[:3]:
        flash(err, 'danger')
    if len(errors) > 3:
        flash(f'另有 {len(errors) - 3} 个文件发送失败', 'warning')
    return redirect(url_for('student_drive.admin_student_drive_detail', student_id=student_id))
