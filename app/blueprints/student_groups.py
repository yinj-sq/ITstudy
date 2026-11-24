"""
学生学习小组蓝图
功能：查看小组信息、加入/退出、共享网盘上传/下载/预览/删除
文件存储：uploads/drive/<group_id>/<uuid>_<filename>
"""
from flask import (Blueprint, request, render_template, redirect,
                   url_for, session, flash, current_app, jsonify)
import json
import os
import re
import uuid
from sqlalchemy import func
from app.extensions import db
from app.models import Student, StudyGroup, GroupFile, GroupJoinRequest, Appeal
from app.decorators import login_required, admin_login_required
from app.services.download_pool import send_large_download
from app.utils import (validate_image_magic_head,
                        read_file_from_disk, delete_file_from_disk, parse_int)

student_groups_bp = Blueprint('student_groups', __name__, url_prefix='')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
                      'mp3', 'wav', 'ogg', 'mp4', 'webm', 'avi',
                      'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
                      'zip', 'rar', '7z', 'py', 'js', 'html', 'css', 'json', 'xml', 'md'}
MAX_FILE_SIZE_MB = 20

# PPTist JSON 数据版本 — 递增可使旧缓存失效并触发重新解析。
# v2：弃用 python-pptx 服务端转换（app/pptx_converter.py，还原度差已停用），
# 统一走 PPTist 浏览器内 pptxtojson 解析；v1 时代缓存（含转换器产物）
# 全部失效，首次打开自动重新解析并以高保真数据回存。
PPTIST_DATA_VERSION = 2

# ── PPTist JSON 存储型 XSS 防护 ─────────────────────────────
# 黑名单策略：整块移除危险标签、on* 事件属性、危险伪协议，
# 保留 PPTist 正文正常富文本（<span>、<br>、data:image 图片等）
_DANGEROUS_TAG_RE = re.compile(
    r'<\s*(script|svg|iframe|object|embed|form|input|button|style|link|meta|math|video|audio)\b[^>]*>'
    r'(?:[\s\S]*?<\s*/\s*\1\s*>)?',
    re.IGNORECASE)
_EVENT_ATTR_RE = re.compile(
    r'\s(?:on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+))',
    re.IGNORECASE)
_DANGEROUS_URI_RE = re.compile(
    r'\b(?:javascript|vbscript|mhtml)\s*:',
    re.IGNORECASE)
# 净化后复查标记（含 HTML 实体解码变体检测，如 &#106;avascript:）
_DANGER_MARK_RE = re.compile(
    r'<\s*(?:script|svg|iframe|object|embed|form|input|button|style|link|meta|math|video|audio)\b'
    r'|\bon[a-z]+\s*='
    r'|\bjavascript\s*:|\bvbscript\s*:|\bmhtml\s*:'
    r'|data\s*:\s*text/html',
    re.IGNORECASE)


def _sanitize_text(value):
    """剔除字符串中的危险 HTML/脚本片段（黑名单删除，保留无害文本）。"""
    v = _DANGEROUS_TAG_RE.sub('', value)
    v = _EVENT_ATTR_RE.sub('', v)
    v = _DANGEROUS_URI_RE.sub('', v)
    return v


def _sanitize_pptist_json(data):
    """递归净化 PPTist JSON 中所有字符串值（防存储型 XSS）。

    - 危险标签整块剔除、on* 事件属性剔除、伪协议剔除
    - HTML 实体编码变体（如 &#106;avascript:）经 unescape 复查，
      命中危险标记则抛 ValueError → 调用方返回 400（fail-closed）
    """
    import html as _html
    if isinstance(data, dict):
        return {k: _sanitize_pptist_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_sanitize_pptist_json(v) for v in data]
    if isinstance(data, str):
        v = _sanitize_text(data)
        # 复查（含 HTML 实体变体）：unescape 后先剔除全部 ASCII 空白再匹配——
        # 浏览器 URL 解析器会剥离 Tab/换行后才解析 scheme，故
        # `java&#10;script:` 解码为 `java\nscript:` 后实际按 `javascript:` 执行；
        # 此前正则要求字母连续，空白字符实体可精准绕过黑名单（已实证）。
        if _DANGER_MARK_RE.search(v) or \
                _DANGER_MARK_RE.search(re.sub(r'\s+', '', _html.unescape(v))):
            raise ValueError('检测到危险 HTML 片段')
        return v
    return data


def _get_current_student():
    """按 session 加载当前学生；学生记录不存在（已被删除但 session 仍有效）时返回 None。

    调用方需对返回值做 None 防御，避免 AttributeError → 500。
    """
    student_id = session.get('student_id')
    return db.session.get(Student, student_id) if student_id else None


def _get_file_content(gf):
    """读取文件内容 — 从磁盘读取"""
    if gf.file_path:
        try:
            return read_file_from_disk(gf.file_path)
        except FileNotFoundError:
            current_app.logger.warning('小组文件丢失: id=%s, path=%s', gf.id, gf.file_path)
    return b''


def _get_preview_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
        return 'image'
    if ext == 'pdf':
        return 'pdf'
    if ext in ('mp3', 'wav', 'ogg'):
        return 'audio'
    if ext in ('mp4', 'webm', 'avi'):
        return 'video'
    if ext in ('txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md'):
        return 'text'
    return 'download'


# ──────────────────────────────────────────────
#  小组主页
# ──────────────────────────────────────────────


@student_groups_bp.route('/groups')
@login_required
def my_groups():
    """学生小组页面"""
    student_id = session.get('student_id')
    student = _get_current_student()
    if not student:
        return redirect(url_for('auth.login'))

    my_group = student.group
    if student.class_id:
        all_groups = StudyGroup.query.filter_by(class_id=student.class_id).order_by(StudyGroup.name).all()
    else:
        all_groups = []

    # 各组人数：模板此前写 `g.members|length`，每组懒加载把**整组学生行**拉出来
    # 只为取长度（N 个小组 = N 次查询）。改为一次分组计数（不带出学生行）。
    member_counts = {}
    if all_groups:
        member_counts = dict(
            db.session.query(Student.group_id, func.count(Student.id))
            .filter(Student.group_id.in_([g.id for g in all_groups]))
            .group_by(Student.group_id).all()
        )

    my_requests = GroupJoinRequest.query.filter_by(
        student_id=student_id, status='pending').all()

    incoming_requests = []
    if my_group and my_group.leader_id == student_id:
        # joinedload(student)：模板每条申请访问 req.student.name /
        # student_number，消除 N+1（申请数不分页）
        from sqlalchemy.orm import joinedload as _jl_req
        incoming_requests = GroupJoinRequest.query.options(
            _jl_req(GroupJoinRequest.student)).filter_by(
            group_id=my_group.id, status='pending', request_type='join'
        ).order_by(GroupJoinRequest.request_time.desc()).all()

    return render_template('student_groups.html',
                           student=student, my_group=my_group,
                           all_groups=all_groups, my_requests=my_requests,
                           member_counts=member_counts,
                           incoming_requests=incoming_requests)


@student_groups_bp.route('/groups/join', methods=['POST'])
@login_required
def join_group():
    """申请加入小组"""
    student_id = session.get('student_id')
    student = _get_current_student()
    group_id = parse_int(request.form.get('group_id'))
    if not group_id:
        flash('请选择小组', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    group = db.get_or_404(StudyGroup, group_id)
    if not student or student.group_id:
        flash('你已经在其他小组中，请先退出', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    if group.class_id != student.class_id:
        flash('只能加入本班级的小组', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    existing = GroupJoinRequest.query.filter_by(
        student_id=student_id, group_id=group_id, request_type='join', status='pending').first()
    if existing:
        flash('你已经提交过申请，请等待审批', 'warning')
        return redirect(url_for('student_groups.my_groups'))
    req = GroupJoinRequest(student_id=student_id, group_id=group_id, request_type='join')
    db.session.add(req)
    db.session.commit()
    flash(f'已申请加入 {group.name} 组', 'success')
    return redirect(url_for('student_groups.my_groups'))


@student_groups_bp.route('/groups/leave', methods=['POST'])
@login_required
def leave_group():
    """退出小组"""
    student_id = session.get('student_id')
    student = _get_current_student()
    if not student or not student.group_id:
        flash('你不在任何小组中', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    group = student.group
    if group.leader_id == student_id:
        flash('组长不能直接退出，请先转让组长', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    student.group_id = None
    db.session.commit()
    flash(f'已退出 {group.name} 组', 'success')
    return redirect(url_for('student_groups.my_groups'))


# ──────────────────────────────────────────────
#  共享网盘（文件存储于 uploads/drive/）
# ──────────────────────────────────────────────


@student_groups_bp.route('/groups/drive')
@login_required
def group_drive():
    """小组共享网盘页面"""
    student = _get_current_student()
    if not student or not student.group:
        flash('请先加入小组', 'danger')
        return redirect(url_for('student_groups.my_groups'))

    group = student.group
    if not group.drive_enabled:
        flash('小组网盘已关闭', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    # 小组网盘文件分页（文件长期累积）
    from app.utils import paginate_query
    from sqlalchemy.orm import joinedload as _jl
    pagination = paginate_query(
        GroupFile.query.options(_jl(GroupFile.uploader)).filter_by(
            group_id=group.id).order_by(GroupFile.upload_time.desc()),
        default_per_page=20, max_per_page=100
    )
    files = pagination.items
    # 已用空间按全组全量求和（原实现只统计当前分页，分页下会低估已用空间）
    total_size = db.session.query(
        func.sum(GroupFile.file_size)
    ).filter(GroupFile.group_id == group.id).scalar() or 0
    max_space = group.max_space_mb * 1024 * 1024

    return render_template('group_drive.html', group=group, files=files,
                           total_size=total_size, max_space=max_space, student=student,
                           pagination=pagination)


@student_groups_bp.route('/groups/drive/upload', methods=['POST'])
@login_required
def drive_upload():
    """上传文件到小组网盘 → 存入 uploads/drive/<group_id>/"""
    student_id = session.get('student_id')
    student = _get_current_student()
    if not student or not student.group:
        flash('请先加入小组', 'danger')
        return redirect(url_for('student_groups.my_groups'))

    group = student.group
    if not group.drive_enabled:
        flash('小组网盘已关闭', 'danger')
        return redirect(url_for('student_groups.group_drive'))
    if not group.upload_enabled:
        flash('网盘上传功能已被管理员禁用', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    file = request.files.get('file')
    if not file or not file.filename:
        flash('请选择文件', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    filename = file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        flash(f'不支持的文件类型: .{ext}', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    # 图片魔数校验：只读文件头（webp 需 12 字节，统一走 validate_image_magic_head；
    # 此前这里仍读 8 字节 → 小组网盘所有 webp 必被误判拒收）
    if not validate_image_magic_head(file, filename):
        flash('图片文件内容与扩展名不符，已拒绝上传', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    # 锁定小组行串行化空间检查（SELECT FOR UPDATE），防并发上传超额（TOCTOU）
    locked_group = StudyGroup.query.filter(StudyGroup.id == group.id).with_for_update().first()
    if not locked_group:
        flash('小组不存在', 'danger')
        return redirect(url_for('student_groups.group_drive'))
    # 流式落盘（save 直写磁盘；大小校验在落盘后按 getsize 执行，超限即删）
    subdir = os.path.join('drive', str(group.id)).replace('\\', '/')
    stored_name = str(uuid.uuid4())[:8] + '_' + filename
    from app.utils import save_stream_to_disk
    ok, msg, rel_path, file_size = save_stream_to_disk(
        file, subdir, stored_name, max_bytes=MAX_FILE_SIZE_MB * 1024 * 1024)
    if not ok:
        flash(msg, 'danger')
        return redirect(url_for('student_groups.group_drive'))
    existing_size = db.session.query(func.sum(GroupFile.file_size)).filter_by(group_id=group.id).scalar() or 0
    if existing_size + file_size > group.max_space_mb * 1024 * 1024:
        from app.utils import delete_file_from_disk as _del_f
        try:
            _del_f(rel_path)
        except Exception:
            pass
        flash(f'小组网盘空间不足（上限 {group.max_space_mb}MB）', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    gf = GroupFile(
        group_id=group.id, uploader_id=student_id,
        filename=stored_name, original_filename=filename,
        file_size=file_size, file_path=rel_path,
    )
    db.session.add(gf)
    try:
        db.session.commit()
    except Exception:
        # DB 提交失败：磁盘文件已成孤儿，回滚后删除
        db.session.rollback()
        from app.utils import delete_file_from_disk as _del_f
        try:
            _del_f(rel_path)
        except Exception:
            pass
        current_app.logger.error('小组网盘上传提交失败，已清理孤儿文件', exc_info=True)
        flash('文件上传失败，请重试', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    if ext in ('pptx', 'ppt'):
        flash(f'文件 "{filename}" 上传成功（首次编辑或预览时将自动转换）', 'success')
    else:
        flash(f'文件 "{filename}" 上传成功', 'success')
    return redirect(url_for('student_groups.group_drive'))


@student_groups_bp.route('/groups/drive/download/<int:file_id>')
@login_required
def drive_download(file_id):
    """下载网盘文件"""
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        return '无权访问', 403
    if not gf.group.drive_enabled:
        return '小组网盘已关闭', 403
    # 磁盘直送 + conditional（此前全读内存 + BytesIO 中转）。
    # inline=1：预览通道 —— 必须**完全没有** Content-Disposition。此前只
    # 观察到 attachment 会让 JitViewer 报"格式不正确"，遂改用 inline；实测
    # inline 同样被 Chromium 拦截（见 utils.strip_inline_content_disposition
    # 的矩阵），JitViewer 拿到的仍是 0 字节。主动内容类型强制 text/plain
    # 防存储型 XSS 的处置不受影响。
    from app.utils import (get_existing_absolute_path, safe_inline_mimetype,
                           strip_inline_content_disposition)
    abs_path = get_existing_absolute_path(gf.file_path)
    if not abs_path:
        return '文件不存在', 404
    inline = request.args.get('inline') == '1'
    mimetype = safe_inline_mimetype(gf.original_filename) if inline else None
    resp = send_large_download(abs_path, conditional=True,
                               download_name=gf.original_filename,
                               as_attachment=not inline, mimetype=mimetype)
    if inline:
        strip_inline_content_disposition(resp)
        # 私有动态内容禁缓存（与 CD 头无关的常规处置）
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@student_groups_bp.route('/groups/drive/preview/<int:file_id>')
@login_required
def drive_preview(file_id):
    """预览网盘文件 — PPTX 走 PPTist 嵌入预览，其他文件使用 JitViewer"""
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        return '无权访问', 403
    if not gf.group.drive_enabled:
        return '小组网盘已关闭', 403

    filename = gf.original_filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    # PPTX/PPT → PPTist 嵌入预览（懒解析）
    if ext in ('pptx', 'ppt'):
        json_url = url_for('student_groups.drive_json', file_id=file_id)
        save_json_url = url_for('student_groups.drive_save_json', file_id=file_id)
        # PPTist 浏览器内解析拉取原始文件：inline 无 CD 头
        download_url = url_for('student_groups.drive_download', file_id=file_id,
                               inline=1)
        back_url = url_for('student_groups.group_drive')
        return render_template('pptist_embed.html',
                               submode='preview',
                               filename=filename,
                               file_id=file_id,
                               json_url=json_url,
                               save_json_url=save_json_url,
                               download_url=download_url,
                               back_url=back_url)

    # JitViewer 预览需 inline URL（无 attachment CD 头）；下载按钮保持 attachment
    file_url = url_for('student_groups.drive_download', file_id=file_id, inline=1)
    download_url = url_for('student_groups.drive_download', file_id=file_id)

    media_type_map = {
        'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
        'bmp': 'image', 'webp': 'image',
        'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio',
        'mp4': 'video', 'webm': 'video',
        'txt': 'text', 'py': 'text', 'js': 'text', 'html': 'text',
        'css': 'text', 'json': 'text', 'xml': 'text', 'md': 'text',
    }
    media_type = media_type_map.get(ext, '')

    return render_template('document_preview.html',
                           filename=filename,
                           file_url=file_url,
                           download_url=download_url,
                           media_type=media_type,
                           back_url=url_for('student_groups.group_drive'))


@student_groups_bp.route('/groups/drive/json/<int:file_id>')
@login_required
def drive_json(file_id):
    """返回 PPTist 兼容的 JSON 数据（带版本校验）"""
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        return jsonify({'error': '无权访问'}), 403
    if not gf.pptist_json:
        return jsonify({'error': '该文件没有预生成的 JSON 数据'}), 404
    try:
        data = json.loads(gf.pptist_json)
    except json.JSONDecodeError:
        return jsonify({'error': 'JSON 数据损坏'}), 500
    # 版本校验：过期则返回 404，触发前端重新解析
    if data.get('_v') != PPTIST_DATA_VERSION:
        return jsonify({'error': 'PPTist 数据版本过旧'}), 404
    from flask import Response
    return Response(gf.pptist_json, mimetype='application/json')


@student_groups_bp.route('/groups/drive/save-json/<int:file_id>', methods=['POST'])
@login_required
def drive_save_json(file_id):
    """保存 PPTist 编辑后的 JSON 数据回数据库
    （结构校验 + 存储型 XSS 净化 + 版本标记 + 大小限制）"""
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        return jsonify({'error': '无权访问'}), 403
    group = db.session.get(StudyGroup, gf.group_id)
    if not group or not group.drive_enabled:
        return jsonify({'error': '小组网盘已关闭'}), 403
    # 只有 PPT 才有 PPTist 数据（否则任意文件可挂 20MB JSON 且不计配额）
    if (gf.original_filename or '').rsplit('.', 1)[-1].lower() not in ('ppt', 'pptx'):
        return jsonify({'error': '仅 PPT 文件支持保存课件数据'}), 400
    data = request.get_json(silent=True)
    # 仅接受 JSON 对象（PPTist 导出格式；顶层 list 读回时 data.get 会 500）
    if not isinstance(data, dict):
        return jsonify({'error': '无效的 JSON 数据'}), 400
    # PPTist 导出格式轻量结构检查：slides 必须为对象数组（每项含 content 等）
    if isinstance(data, dict) and 'slides' in data:
        slides = data['slides']
        if not isinstance(slides, list) or not all(isinstance(s, dict) for s in slides):
            return jsonify({'error': 'PPTist 数据结构无效'}), 400
    # 存储型 XSS 净化：所有字符串值剔除危险 HTML/脚本片段（命中即拒绝 400）
    try:
        data = _sanitize_pptist_json(data)
    except ValueError:
        return jsonify({'error': '包含危险 HTML 内容'}), 400
    if isinstance(data, dict):
        data['_v'] = PPTIST_DATA_VERSION
    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # 防御：无限制 JSON 存库会撑爆数据库（与课堂课件缓存端点同口径 20MB；
    # 全局 JSON 请求上限 25MB 在其之上）
    new_len = len(json_str.encode('utf-8'))
    if new_len > 20 * 1024 * 1024:
        return jsonify({'error': 'PPTist 数据超过 20MB 限制'}), 413
    # 课件数据计入小组空间（文件体积 + 其余文件课件数据 + 本次数据）
    used = db.session.query(func.coalesce(func.sum(GroupFile.file_size), 0)).filter(
        GroupFile.group_id == gf.group_id).scalar() or 0
    other_json = db.session.query(func.coalesce(func.sum(
        func.octet_length(GroupFile.pptist_json)), 0)).filter(
        GroupFile.group_id == gf.group_id, GroupFile.id != gf.id).scalar() or 0
    if used + other_json + new_len > group.max_space_mb * 1024 * 1024:
        return jsonify({'error': '小组网盘空间不足，无法保存课件数据'}), 413
    gf.pptist_json = json_str
    db.session.commit()
    return jsonify({'ok': True})


@student_groups_bp.route('/groups/drive/convert/<int:file_id>')
@login_required
def drive_convert(file_id):
    """[兼容] 旧版上传后转换入口 → 重定向到编辑页面（懒转换）"""
    return redirect(url_for('student_groups.drive_edit', file_id=file_id))


@student_groups_bp.route('/groups/drive/edit/<int:file_id>')
@login_required
def drive_edit(file_id):
    """编辑网盘 PPTX 文件 — PPTist iframe 嵌入，优先加载缓存 JSON，无则触发懒解析"""
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        return '无权访问', 403

    filename = gf.original_filename
    json_url = url_for('student_groups.drive_json', file_id=file_id)
    save_json_url = url_for('student_groups.drive_save_json', file_id=file_id)
    # PPTist 浏览器内解析拉取原始文件：inline 无 CD 头
    download_url = url_for('student_groups.drive_download', file_id=file_id,
                           inline=1)
    back_url = url_for('student_groups.group_drive')
    return render_template('pptist_embed.html',
                           submode='editor',
                           filename=filename,
                           file_id=file_id,
                           json_url=json_url,
                           save_json_url=save_json_url,
                           download_url=download_url,
                           back_url=back_url)


@student_groups_bp.route('/groups/drive/delete/<int:file_id>', methods=['POST'])
@login_required
def drive_delete(file_id):
    """删除网盘文件（磁盘+数据库）"""
    student_id = session.get('student_id')
    student = _get_current_student()
    gf = db.get_or_404(GroupFile, file_id)
    if not student or student.group_id != gf.group_id:
        flash('无权操作', 'danger')
        return redirect(url_for('student_groups.group_drive'))
    if not student or (gf.uploader_id != student_id and student.group.leader_id != student_id):
        flash('只有上传者或组长才能删除文件', 'danger')
        return redirect(url_for('student_groups.group_drive'))

    # 先删 DB 记录再删磁盘（与上传路径的失败防护对称）：commit 失败时
    # 磁盘文件保留（仅成孤儿，可再清理），反之记录在而文件失 → 下载 404
    file_path = gf.file_path
    db.session.delete(gf)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.error('删除小组文件失败: file_id=%s', file_id, exc_info=True)
        flash('删除文件失败，请重试', 'danger')
        return redirect(url_for('student_groups.group_drive'))
    delete_file_from_disk(file_path)
    flash('文件已删除', 'success')
    return redirect(url_for('student_groups.group_drive'))


# ──────────────────────────────────────────────
#  管理员：网盘管理
# ──────────────────────────────────────────────


@student_groups_bp.route('/admin/groups/<int:group_id>/drive-settings', methods=['POST'])
@admin_login_required
def admin_drive_settings(group_id):
    """管理小组设置 — 名称、组长、口号、网盘开关、容量、上传权限"""
    group = db.get_or_404(StudyGroup, group_id)
    name = request.form.get('name', '').strip()
    slogan = request.form.get('slogan', '').strip()

    if name:
        dup = StudyGroup.query.filter(
            StudyGroup.name == name, StudyGroup.class_id == group.class_id,
            StudyGroup.id != group_id
        ).first()
        if dup:
            flash(f'该班级已存在 {name} 组', 'danger')
            return redirect(url_for('class_management.admin_groups', class_id=group.class_id))
        group.name = name
    if slogan is not None:
        group.slogan = slogan

    # 仅在表单提交时才更新 drive_enabled（切换开关），未提交时保持原值
    if request.form.get('drive_enabled') is not None:
        group.drive_enabled = request.form.get('drive_enabled') == 'true'
    if request.form.get('upload_enabled') is not None:
        group.upload_enabled = request.form.get('upload_enabled') == 'true'
    # 容量解析：非数字/越界时回退默认值 50MB，避免 ValueError → 500；
    # 上界 100GB 防止误填超大值导致空间判断失效
    try:
        space_mb = int(request.form.get('max_space_mb', '50') or '50')
    except (TypeError, ValueError):
        space_mb = 50
    if space_mb < 1:
        space_mb = 50
    if space_mb > 102400:
        space_mb = 102400
    group.max_space_mb = space_mb
    if request.form.get('leader_id') is not None:
        lid = request.form.get('leader_id', '').strip()
        new_leader_id = parse_int(lid) if lid else None
        # 组长必须存在且属于本组所在班级（与 add_group / edit_group /
        # api_groups._validate_leader 一致）。此前本端点缺该校验：构造 POST
        # 可把外班学生设为组长并自动加入本组，而小组网盘按 group_id 判权，
        # 等于把本组文件访问权交给外班学生。UI 下拉虽按班级过滤，但服务端
        # 必须自证。
        if new_leader_id:
            new_leader = db.session.get(Student, new_leader_id)
            if new_leader is None:
                flash('组长不存在', 'danger')
                return redirect(url_for('class_management.admin_groups',
                                        class_id=group.class_id))
            if new_leader.class_id != group.class_id:
                flash('组长必须属于该小组所在班级', 'danger')
                return redirect(url_for('class_management.admin_groups',
                                        class_id=group.class_id))
        group.leader_id = new_leader_id
        if new_leader_id:
            new_leader = db.session.get(Student, new_leader_id)
            if new_leader and new_leader.group_id != group.id:
                new_leader.group_id = group.id
    db.session.commit()
    flash(f'{group.name} 组设置已更新', 'success')
    return redirect(url_for('class_management.admin_groups', class_id=group.class_id))


@student_groups_bp.route('/admin/groups/<int:group_id>/drive-clear', methods=['POST'])
@admin_login_required
def admin_drive_clear(group_id):
    """清空小组网盘（磁盘+数据库）"""
    group = db.get_or_404(StudyGroup, group_id)
    files = GroupFile.query.filter_by(group_id=group_id).all()
    count = len(files)

    # 先删数据库记录并提交，成功后再清理磁盘：此前先删盘后 commit，
    # commit 失败时记录仍在而全部文件已 404
    paths = [gf.file_path for gf in files]
    GroupFile.query.filter_by(group_id=group_id).delete()
    db.session.commit()
    for rel in paths:
        delete_file_from_disk(rel)
    flash(f'已清空 {group.name} 组网盘（{count} 个文件）', 'success')
    return redirect(url_for('class_management.admin_groups', class_id=group.class_id))


@student_groups_bp.route('/admin/groups/drive-all-toggle', methods=['POST'])
@admin_login_required
def admin_drive_all_toggle():
    """一键开关所有班级网盘"""
    enable = request.form.get('enable_all', '') == 'true'
    StudyGroup.query.update({'drive_enabled': enable})
    db.session.commit()
    flash('已' + ('开启' if enable else '关闭') + '所有小组网盘', 'success')
    return redirect(url_for('class_management.admin_groups'))


# ──────────────────────────────────────────────
#  组长管理
# ──────────────────────────────────────────────


@student_groups_bp.route('/groups/approve/<int:req_id>', methods=['POST'])
@login_required
def approve_request(req_id):
    """组长审批加入申请"""
    student_id = session.get('student_id')
    req = db.get_or_404(GroupJoinRequest, req_id)
    student = _get_current_student()
    my_group = student.group if student else None
    if not my_group or my_group.leader_id != student_id:
        flash('只有组长才能审批申请', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    if req.group_id != my_group.id:
        flash('这不是你小组的申请', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    # 只处理待审申请：否则组员退组后，组长可重新"批准"其旧的已批准申请，
    # 未经本人同意把人拉回组内（并获得网盘权限）
    if req.status != 'pending':
        flash('该申请已处理', 'warning')
        return redirect(url_for('student_groups.my_groups'))

    applicant = db.session.get(Student, req.student_id)
    if not applicant:
        flash('申请人不存在', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    if applicant.group_id:
        flash(f'{applicant.name} 已在其他小组中', 'danger')
        req.status = 'rejected'
        db.session.commit()
        return redirect(url_for('student_groups.my_groups'))

    req.status = 'approved'
    applicant.group_id = my_group.id
    db.session.commit()
    flash(f'{applicant.name} 已加入 {my_group.name} 组', 'success')
    return redirect(url_for('student_groups.my_groups'))


@student_groups_bp.route('/groups/reject/<int:req_id>', methods=['POST'])
@login_required
def reject_request(req_id):
    """组长拒绝加入申请"""
    student_id = session.get('student_id')
    req = db.get_or_404(GroupJoinRequest, req_id)
    student = _get_current_student()
    my_group = student.group if student else None
    if not my_group or my_group.leader_id != student_id or req.group_id != my_group.id:
        flash('无权操作', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    req.status = 'rejected'
    db.session.commit()
    flash('已拒绝该申请', 'success')
    return redirect(url_for('student_groups.my_groups'))


@student_groups_bp.route('/groups/update', methods=['POST'])
@login_required
def update_group():
    """组长更新小组设置（口号、转让组长）"""
    student_id = session.get('student_id')
    student = _get_current_student()
    my_group = student.group if student else None
    if not my_group or my_group.leader_id != student_id:
        flash('只有组长才能修改小组设置', 'danger')
        return redirect(url_for('student_groups.my_groups'))

    slogan = request.form.get('slogan', '').strip()
    new_leader_id = parse_int(request.form.get('new_leader_id'))
    if slogan is not None:
        # 长度与字符限制（纵深防御）：slogan 会渲染到管理员页面的
        # onclick JS 字符串中，模板侧已用 tojson 转义，此处防止超长/异常内容入库
        if len(slogan) > 50:
            flash('口号不能超过50个字符', 'danger')
            return redirect(url_for('student_groups.my_groups'))
        my_group.slogan = slogan
    if new_leader_id:
        new_leader = db.session.get(Student, new_leader_id)
        if new_leader and new_leader.group_id == my_group.id:
            my_group.leader_id = new_leader.id
            flash(f'组长已转让给 {new_leader.name}', 'success')
        else:
            flash('该学生不在本组中', 'danger')

    db.session.commit()
    if not new_leader_id:
        flash('小组设置已更新', 'success')
    return redirect(url_for('student_groups.my_groups'))


@student_groups_bp.route('/groups/kick/<int:member_id>', methods=['POST'])
@login_required
def kick_member(member_id):
    """组长移除组员"""
    student_id = session.get('student_id')
    student = _get_current_student()
    my_group = student.group if student else None
    if not my_group or my_group.leader_id != student_id:
        flash('只有组长才能移除组员', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    member = db.get_or_404(Student, member_id)
    if member.group_id != my_group.id:
        flash('该学生不在本组中', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    if member.id == student_id:
        flash('组长不能移除自己，请先转让组长', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    member.group_id = None
    db.session.commit()
    flash(f'{member.name} 已被移出小组', 'success')
    return redirect(url_for('student_groups.my_groups'))


# ──────────────────────────────────────────────
#  学生申诉
# ──────────────────────────────────────────────


@student_groups_bp.route('/groups/appeal', methods=['POST'])
@login_required
def send_appeal():
    """学生发送申诉"""
    student_id = session.get('student_id')
    message = request.form.get('message', '').strip()
    if not message:
        flash('请输入申诉内容', 'danger')
        return redirect(url_for('student_groups.my_groups'))
    if len(message) > 200:
        flash('申诉内容不超过200字', 'danger')
        return redirect(url_for('student_groups.my_groups'))

    appeal = Appeal(student_id=student_id, message=message)
    db.session.add(appeal)
    db.session.commit()
    flash('申诉已发送', 'success')
    return redirect(url_for('student_groups.my_groups'))


@student_groups_bp.route('/admin/appeal/dismiss/<int:appeal_id>', methods=['POST'])
@admin_login_required
def dismiss_appeal(appeal_id):
    """管理员关闭申诉"""
    appeal = db.get_or_404(Appeal, appeal_id)
    appeal.is_read = True
    db.session.commit()
    return redirect(url_for('classroom.admin_classroom'))


@student_groups_bp.route('/admin/appeal/clear-all', methods=['POST'])
@admin_login_required
def clear_all_appeals():
    """清除所有已读申诉"""
    Appeal.query.filter_by(is_read=True).delete()
    db.session.commit()
    flash('已清除所有已处理申诉', 'success')
    return redirect(url_for('classroom.admin_classroom'))


# ──────────────────────────────────────────────
#  PPTist 在线PPT编辑（编辑由 PPTist 原生功能：上传/导入/演示/导出）
# ──────────────────────────────────────────────

@student_groups_bp.route('/pptist')
@login_required
def pptist_editor():
    """打开 PPTist 原生在线编辑器（由其原生上传入口导入 PPT 文件）"""
    return redirect('/static/pptist/index.html')
