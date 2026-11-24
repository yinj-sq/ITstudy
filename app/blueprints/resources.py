from flask import Blueprint, request, render_template, redirect, url_for, session, flash, jsonify, abort
from flask import current_app, Response
from datetime import datetime
import os
import time
import re
import uuid
import shutil
import hashlib
import threading
import json as _json
import tempfile
import html as _html
import secrets
from itsdangerous import BadSignature, URLSafeTimedSerializer
from app.extensions import db, cache
from app.models import (Resource, Log, Exam, Subject, ResourceQuizResult, LearningActivity,
                         StudentWork, WorkEvaluation, TeachingSession, ExcellenceThreshold,
                         Teacher, Student, Survey, SurveyAnswer, SurveyQuestion, SystemConfig,
                         teacher_subject, resource_share, resource_audience)
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from app.decorators import (admin_login_required, authenticated_required, login_required,
                            teacher_login_required, teacher_api_required)
from app.utils import (secure_filename_with_unicode, inject_quiz_collector, json_body_or_empty,                       is_html_injected,
                       get_subjects_cached, get_schedules_cached,
                       invalidate_lookup_cache, all_chunks_present, parse_int,
                       PRIVATE_UPLOAD_PREFIXES, adapt_courseware_html)
from app.services.resource_access import (
    teacher_can_edit, teacher_can_view, teacher_subject_allowed,
    teacher_subjects, teacher_visible_resources, teacher_class_ids,
    teacher_can_use_resource,
    student_classroom_scoped_resources, classroom_scope_signature,
    student_can_access_resource,
)
from app.services import quiz_analysis_cache
from app.decorators import teacher_edit_required

resources_bp = Blueprint('resources', __name__, url_prefix='')
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _session_teacher_id():
    if session.get('is_admin'):
        return None
    return session.get('teacher_id') if session.get('is_teacher') else None


def _session_is_teacher_editor():
    return bool(_session_teacher_id())


def _resource_dir_for_session(title):
    """教师资源目录加教师前缀，避免跨教师同名标题互相覆盖。"""
    base = _resource_dir_name(title)
    teacher_id = _session_teacher_id()
    if base and teacher_id:
        return f't{teacher_id}_{base}'
    return base


def _available_subjects():
    teacher_id = _session_teacher_id()
    if teacher_id:
        return teacher_subjects(teacher_id)
    return get_subjects_cached()

# static/uploads 下的系统目录（网盘/作品/答案/活动文档等）。资源标题或目录参数
# 清洗后撞上这些名字时，课件会写进私有目录、删资源时还会把整个系统目录删掉
_RESERVED_UPLOAD_DIRS = frozenset(
    p[len('/static/uploads/'):].strip('/') for p in PRIVATE_UPLOAD_PREFIXES
    if p.startswith('/static/uploads/')) | {'group_files'}

# 资源课件目录需内联 HTML，故只拒绝可执行/脚本类型；上传页分块、整文件上传、
# 编辑页新增/替换三处入口共用，避免规则漂移。
_RESOURCE_REJECT_EXTS = frozenset({
    'exe', 'bat', 'cmd', 'com', 'msi', 'msix', 'scr', 'vbs', 'ps1',
    'dll', 'so', 'sh', 'pyc', 'jar',
})


def _resource_reject_message(path):
    """资源上传路径命中禁止类型时返回明确提示，否则返回空串。"""
    ext = os.path.splitext(path or '')[1].lower().lstrip('.')
    if ext in _RESOURCE_REJECT_EXTS:
        return f'不允许上传可执行文件: {path}'
    return ''


def _resource_dir_name(raw):
    """资源标题/目录参数 → static/uploads 下的目录名；清洗后为空或为系统目录名时返回 ''。"""
    name = secure_filename_with_unicode(raw or '')
    if not name or name.lower() in _RESERVED_UPLOAD_DIRS:
        return ''
    return name


def _resource_dir_deletable(dir_name, res_id):
    """删资源时能否整目录删除：非系统目录，且没有别的资源仍指向该目录
    （跨学科同名资源共用同一目录，删一个不能连带删掉另一个的文件）。"""
    if not dir_name or dir_name.lower() in _RESERVED_UPLOAD_DIRS:
        return False
    return Resource.query.filter(
        Resource.id != res_id,
        Resource.url.startswith(f'/static/uploads/{dir_name}/', autoescape=True),
    ).first() is None

# 分块上传合并单文件上限：50GB（≈ 前端 5MB × 10000 块上限），
# 覆盖单文件 >2GB 的教学资源（4K 视频等），防恶意拼出无界文件
MAX_RESOURCE_FILE_MERGE_BYTES = 50 * 1024 * 1024 * 1024

# /study 资源缓存重建锁：单进程内串行化重建，防缓存 stampede
_study_build_lock = threading.Lock()


_UPLOAD_SNAPSHOT_TTL = 900


def _upload_dir_snapshot(dir_name):
    """上传目录文件清单快照（TTL 900s，键 study:files:<dir>）。

    只做 os.walk 元数据扫描，不读取 HTML 正文；测验采集器检测拆到
    _upload_dir_collectors()，仅编辑/检测页按需调用。此前列表页每 5 分钟
    首次访问会逐 HTML 读全文（8227 文件目录实测约 0.2s，Windows 杀毒软件
    下可达数秒），是菜单页间歇性变慢的主要来源。
    """
    key = f'study:files:{dir_name}'
    snap = cache.get(key)
    if isinstance(snap, dict) and 'files' in snap:
        if 'version' not in snap:
            # 升级前缓存无版本号：补写并落回缓存，避免 collectors 键每次变化
            snap['version'] = uuid.uuid4().hex
            cache.set(key, snap, timeout=_UPLOAD_SNAPSHOT_TTL)
        return snap
    dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
    files = []
    if os.path.isdir(dir_path):
        for root, _, filenames in os.walk(dir_path):
            for fn in filenames:
                if fn.startswith('.') or fn.endswith('.bak'):
                    # .bak 是注入备份，不是学生/教师文件；曾出现在编辑页并
                    # 可勾选属性，但保存时被排除，造成“属性不生效”的假象。
                    continue
                rel = os.path.relpath(os.path.join(root, fn),
                                      dir_path).replace('\\', '/')
                ext = fn.rsplit('.', 1)[-1].lower() if '.' in fn else ''
                files.append({'name': rel, 'ext': ext})
    snap = {'files': files, 'version': uuid.uuid4().hex}
    cache.set(key, snap, timeout=_UPLOAD_SNAPSHOT_TTL)
    return snap


def _upload_dir_collectors(dir_name, snap=None):
    """按需探测 HTML 是否含 ITSTUDY_QUIZ_COLLECTOR（编辑/检测页专用）。

    缓存键带文件清单快照版本：写路径删除 study:files 后版本变化，旧
    collectors 缓存自然失效，无需逐处双删。
    """
    snap = snap or _upload_dir_snapshot(dir_name)
    version = snap.get('version') or 'legacy'
    key = f'study:collectors:{dir_name}:{version}'
    cached = cache.get(key)
    if isinstance(cached, dict):
        return cached
    dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
    collectors = {}
    for entry in snap.get('files') or []:
        rel = entry.get('name') or ''
        if not rel.lower().endswith(('.html', '.htm')):
            continue
        has_collector = False
        try:
            with open(os.path.join(dir_path, rel), 'r',
                      encoding='utf-8', errors='ignore') as hf:
                has_collector = 'ITSTUDY_QUIZ_COLLECTOR' in hf.read()
        except Exception:
            current_app.logger.debug(
                '测验采集器检测失败: %s', rel, exc_info=True)
        collectors[rel] = has_collector
    cache.set(key, collectors, timeout=_UPLOAD_SNAPSHOT_TTL)
    return collectors


# ════════════════════════════════════════════════════════════════
# 注入前检测（P0）：待检测文件、临时演练页、成绩抓取回报、按文件应用
# ════════════════════════════════════════════════════════════════
_QUIZ_CHECK_MAX_BYTES = 20 * 1024 * 1024
_QUIZ_CHECK_TTL_SECONDS = 24 * 60 * 60  # 覆盖一次完整资源检测会话；服务重启/更新仍应重新检测
_QUIZ_CHECK_TOKEN_RE = re.compile(r'^[a-f0-9]{32}$')


def _student_resource_out_of_scope(resource):
    """学生直接访问资源时，校验是否在「当前授课教师范围 + 公开/内置」内。

    与 /study 列表同口径：任课教师范围（自建全量、共享按学科）且不要求
    show_in_student（教师课堂展示即授权）；无任课教师时仅公开/内置资源
    可用——不再回退全局列表，杜绝学生通过直链看到全部资源。
    """
    student_id = session.get('student_id')
    if not student_id or not resource:
        return True
    student = db.session.get(Student, student_id)
    if not student:
        return True
    return not student_can_access_resource(resource, student)


def _quiz_check_dir():
    path = os.path.join(_BASE, 'data', 'quiz_check')
    os.makedirs(path, exist_ok=True)
    return path


def _quiz_check_cleanup(max_age=_QUIZ_CHECK_TTL_SECONDS):
    root = _quiz_check_dir()
    cutoff = time.time() - max_age
    try:
        for fn in os.listdir(root):
            fp = os.path.join(root, fn)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except OSError:
                pass
    except OSError:
        pass


def _quiz_check_meta_path(token):
    return os.path.join(_quiz_check_dir(), f'{token}.json')


def _quiz_check_html_path(token):
    return os.path.join(_quiz_check_dir(), f'{token}.html')


def _quiz_check_meta(token):
    if not _QUIZ_CHECK_TOKEN_RE.fullmatch(token or ''):
        return None
    try:
        with open(_quiz_check_meta_path(token), encoding='utf-8') as f:
            meta = _json.load(f)
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    try:
        created = float(meta.get('created') or 0)
    except (TypeError, ValueError):
        return None
    if time.time() - created > _QUIZ_CHECK_TTL_SECONDS:
        _quiz_check_remove(token)
        return None
    return meta


def _quiz_check_remove(token):
    for suffix in ('.json', '.html', '.source.html', '.source.html.bak'):
        try:
            os.remove(os.path.join(_quiz_check_dir(), token + suffix))
        except OSError:
            pass


def _quiz_pending_files(res):
    try:
        files = _json.loads(res.quiz_pending_files or '[]')
    except Exception:
        return []
    return [f for f in files if isinstance(f, str) and f]


def _quiz_check_resource(res_id):
    res = db.session.get(Resource, res_id)
    if not res:
        abort(404)
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        abort(403)
    return res


def _quiz_rel_abs(res, raw):
    """校验资源内 HTML 相对路径，返回规范化相对路径与绝对路径。"""
    rel = str(raw or '').replace('\\', '/').lstrip('/')
    if (not rel or len(rel) > 500 or '\x00' in rel or
            '..' in rel.split('/') or
            not rel.lower().endswith(('.html', '.htm'))):
        return None, None
    rel = os.path.normpath(rel).replace('\\', '/')
    if rel.startswith('../') or rel == '..':
        return None, None
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return None, None
    base = os.path.realpath(os.path.join(_BASE, 'static', 'uploads', dir_name))
    fp = os.path.realpath(os.path.join(base, rel))
    if fp == base or not fp.startswith(base + os.sep) or not os.path.isfile(fp):
        return None, None
    return rel, fp


def _quiz_source_file_info(res, raw):
    """客户端 source_file → (规范化路径, quiz_key, 错误)。空值兼容旧 SDK。"""
    if raw in (None, ''):
        return '', 'legacy', None
    if not isinstance(raw, str):
        return None, None, '来源文件格式无效'
    rel, _fp = _quiz_rel_abs(res, raw)
    if not rel:
        return None, None, '来源文件不存在或不在资源目录内'
    key_src = os.path.normcase(rel).replace('\\', '/')
    return rel, hashlib.sha256(key_src.encode('utf-8')).hexdigest()[:32], None


def _quiz_dry_run_status(payload):
    """根据试运行回报判定：pass/partial/fail。"""
    answers = payload.get('answers') if isinstance(payload, dict) else None
    answer_count = len(answers) if isinstance(answers, dict) else 0
    has_score = False
    if isinstance(payload, dict):
        if payload.get('total_score') is not None:
            has_score = True
        if payload.get('correct_count') is not None:
            has_score = True
        if payload.get('grade'):
            has_score = True
    if has_score and answer_count > 0:
        return 'pass', '已捕获答案和成绩'
    if has_score:
        return 'pass', '已捕获成绩'
    if answer_count > 0:
        return 'partial', '已捕获答案，但未捕获成绩'
    return 'fail', '未捕获答案或成绩'


def _quiz_js_string(value):
    return _json.dumps(str(value or ''), ensure_ascii=False).replace('</', '<\\/')


def _build_quiz_check_html(res, rel, token):
    """生成临时演练页：先按正式方式注入 SDK，再打开 dry-run 开关。"""
    _rel, src_abs = _quiz_rel_abs(res, rel)
    if not src_abs:
        return None
    if os.path.getsize(src_abs) > _QUIZ_CHECK_MAX_BYTES:
        return None
    try:
        with open(src_abs, encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return None

    # 复用正式注入逻辑；原文件已有采集器时函数返回 False，但页面本身可直接试运行
    temp_source = os.path.join(_quiz_check_dir(), f'{token}.source.html')
    try:
        with open(temp_source, 'w', encoding='utf-8') as f:
            f.write(content)
        inject_quiz_collector(temp_source, res.id, rel)
        with open(temp_source, encoding='utf-8', errors='ignore') as f:
            content = f.read()
    finally:
        try:
            os.remove(temp_source)
        except OSError:
            pass
        try:
            os.remove(temp_source + '.bak')
        except OSError:
            pass

    dir_name = _resource_upload_dir(res) or ''
    dry_script = (
        '<script>\n'
        'window.__ITSTUDY_QUIZ_DRY_RUN__ = true;\n'
        'window.__INJECT_RESOURCE_ID__ = ' + _json.dumps(res.id) + ';\n'
        'window.__ITSTUDY_QUIZ_SOURCE_FILE__ = ' + _quiz_js_string(rel) + ';\n'
        'window.__ITSTUDY_QUIZ_TEST_TOKEN__ = ' + _quiz_js_string(token) + ';\n'
        'window.__ITSTUDY_QUIZ_REPORT_URL__ = ' + _quiz_js_string(
            url_for('resources.resource_quiz_check_report',
                    res_id=res.id, token=token)) + ';\n'
        'window.__ITSTUDY_QUIZ_CSRF__ = ' + _quiz_js_string(
            session.get('csrf_token', '')) + ';\n'
        '</script>'
    )
    head_insert = dry_script
    if not re.search(r'<base\b', content, re.IGNORECASE):
        base_href = f'/static/uploads/{dir_name}/'
        head_insert = (f'<base href="{_html.escape(base_href, quote=True)}">\n'
                       + dry_script)
    if re.search(r'<head[^>]*>', content, re.IGNORECASE):
        content = re.sub(
            r'<head[^>]*>', lambda m: m.group(0) + '\n' + head_insert,
            content, count=1, flags=re.IGNORECASE)
    else:
        content = head_insert + '\n' + content

    banner = (
        '<div id="itstudy-quiz-dryrun-banner" style="position:fixed;top:0;'
        'left:0;right:0;z-index:2147483647;background:#7c3aed;color:#fff;'
        'font:13px/1.8 sans-serif;text-align:center;padding:4px 10px;">'
        '模拟检测模式 · 本次答题不会保存成绩 · 完成后可关闭本页</div>')
    if re.search(r'<body[^>]*>', content, re.IGNORECASE):
        content = re.sub(
            r'<body[^>]*>', lambda m: m.group(0) + '\n' + banner,
            content, count=1, flags=re.IGNORECASE)
    else:
        content = banner + '\n' + content
    return content


def _invalidate_quiz_resource(res):
    _invalidate_study_caches(_resource_upload_dir(res) or '')
    cache.delete('courseware:dir_map')


def _build_study_resource_data(resources_list, include_files=True):
    """构建 /study 资源数据（性能优化版）

    - 活动批量加载（IN 查询），消除逐资源 N+1
    - 文件清单按目录独立缓存（TTL 300s），避免每次重建 os.walk 整个上传目录
    """
    res_ids = [r.id for r in resources_list]
    activities_map = {}
    surveys_map = {}
    if res_ids:
        active_res = LearningActivity.query.filter(
            LearningActivity.resource_id.in_(res_ids),
            LearningActivity.is_active.is_(True)
        ).order_by(LearningActivity.sort_order,
                   LearningActivity.created_at.desc()).all()
        for a in active_res:
            activities_map.setdefault(a.resource_id, []).append({
                'id': a.id,
                'title': a.title,
                'require_upload': a.require_upload,
                'document_path': a.document_path,
            })
        # 问卷：仅已发布的进入 /study 卡片与默认课堂树（草稿在问卷管理页管理；
        # 该结构进入共享缓存，不能随角色过滤，发布状态全校一致）
        published_surveys = Survey.query.filter(
            Survey.resource_id.in_(res_ids),
            Survey.status == 'published'
        ).order_by(Survey.sort_order, Survey.created_at.desc()).all()
        for s in published_surveys:
            surveys_map.setdefault(s.resource_id, []).append({
                'id': s.id,
                'title': s.title,
            })

    resource_data = []
    for res in resources_list:
        files = []
        homepage_file = None
        homework_files = []
        file_perms = {}
        is_external_link = False

        if res.homework_files:
            try:
                homework_files = _json.loads(res.homework_files)
            except Exception:
                homework_files = []
        if res.file_permissions:
            try:
                file_perms = _json.loads(res.file_permissions)
            except Exception:
                file_perms = {}
        homework_count = len(homework_files)
        is_file_resource = bool(
            res.url and res.url.startswith('/static/uploads/'))

        if res.url and (res.url.startswith('http://') or res.url.startswith('https://')):
            is_external_link = True
        elif is_file_resource and include_files:
            url_path = res.url.replace('/static/uploads/', '', 1)
            parts = url_path.split('/')
            if len(parts) >= 2:
                dir_name = parts[0]
                url_file = '/'.join(parts[1:])
                files = _upload_dir_snapshot(dir_name)['files']
                # 用缓存的文件清单补全权限/主页/作业标记
                full_files = []
                for f in files:
                    rel = f['name']
                    ext = f['ext']
                    # 课堂页衍生文件（思维导图/PPTist 缓存）不进文件卡片列表
                    if rel.endswith('.pptist.json') or (
                            (rel.startswith('mindmap-') or rel.startswith('flow-')) and rel.endswith('.json')):
                        continue
                    is_homepage = (rel == url_file)
                    is_homework = rel in homework_files
                    perm = file_perms.get(rel, {})
                    if is_homework:
                        can_show = True
                        can_download = True
                    elif is_homepage:
                        can_show = True
                        can_download = perm.get('download', True)
                    else:
                        can_show = perm.get('show', True)
                        can_download = perm.get('download', True)
                    fdata = {
                        'name': rel,
                        'url': f'/static/uploads/{dir_name}/{rel}',
                        'ext': ext,
                        'is_homepage': is_homepage,
                        'is_homework': is_homework,
                        'can_show': can_show,
                        'can_download': can_download
                    }
                    if is_homepage:
                        homepage_file = fdata
                    full_files.append(fdata)
                files = full_files

        homework_list = [f for f in files
                         if f.get('is_homework') and not f.get('is_homepage')]
        resource_data.append({
            'res': {
                'id': res.id,
                'title': res.title,
                'url': res.url,
                'subject_id': res.subject_id,
                'show_in_student': res.show_in_student,
                'show_in_classroom': res.show_in_classroom,
                'quiz_mode': res.quiz_mode or 'inject'
            },
            'files': sorted(files, key=lambda x: (not x.get('is_homepage', False), not x.get('is_homework', False), x['name'])),
            'homepage_file': homepage_file,
            'homework_files': homework_list,
            'visible_files': [f for f in files if f.get('can_show', True) and not f.get('is_homework')],
            'is_external_link': is_external_link,
            'is_file_resource': is_file_resource,
            'homework_count': (len(homework_list) if include_files
                               else homework_count),
            'file_count': len(files) if include_files else None,
            'activities': activities_map.get(res.id, []),
            'surveys': surveys_map.get(res.id, [])
        })
    return resource_data


def _resource_subject_id(resource_entry):
    """兼容缓存中的 dict 资源和未缓存时的 SQLAlchemy 模型资源。"""
    res = (resource_entry or {}).get('res')
    if isinstance(res, dict):
        return res.get('subject_id')
    return getattr(res, 'subject_id', None)


# 示例学习资源
study_resources = [
    {"title": "Python基础教程", "url": "https://docs.python.org/zh-cn/3/tutorial/"},
    {"title": "Flask官方文档", "url": "https://flask.palletsprojects.com/zh-cn/latest/"},
    {"title": "Bootstrap中文文档", "url": "https://www.bootcss.com/"}
]


@resources_bp.route('/admin/resources', methods=['GET', 'POST'])
@admin_login_required
def admin_resources():
    """学习资源管理页面"""
    if request.method == 'POST':
        title = request.form.get('title')
        url = request.form.get('url')
        subject_id = request.form.get('subject_id', '').strip()
        if title and url:
            # URL 白名单（与首页文件/课堂条目校验口径对齐）：http(s) 外链
            # 或站内课件路径；拒绝目录漂移形态（/static/uploads/../ 等）
            url_ok = url.startswith(('http://', 'https://')) or (
                url.startswith('/static/uploads/') and '..' not in url.split('/'))
            if not url_ok:
                flash('资源链接仅支持 http(s) 外链或站内课件路径（/static/uploads/…）')
            else:
                resource = Resource(title=title, url=url,
                                    subject_id=parse_int(subject_id),
                                    creator_type='admin',
                                    creator_name=session.get('admin_name') or '管理员')
                db.session.add(resource)
                log = Log(
                    user_id=0,
                    user_type='admin',
                    action='添加学习资源',
                    detail=f'资源标题: {title}',
                    time=datetime.now()
                )
                db.session.add(log)
                db.session.commit()
                cache.delete('study:resources:student')
                cache.delete('study:resources:classroom')
                flash('学习资源已添加')
        else:
            flash('标题和链接不能为空')
    # 分页渲染（资源增长后避免单页全量加载）；joinedload 消除逐资源
    # 查 subject 的 N+1
    from app.utils import paginate_query
    from sqlalchemy.orm import joinedload as _jl
    pagination = paginate_query(
        Resource.query.options(_jl(Resource.subject)).order_by(Resource.id.desc()),
        default_per_page=20, max_per_page=100
    )
    resources_list = pagination.items
    subjects = get_subjects_cached()

    # 批量加载活动数量（消除循环内逐资源 count 的 N+1）
    from sqlalchemy import func as _sa_func
    res_ids = [r.id for r in resources_list]
    act_counts = {}
    if res_ids:
        act_rows = db.session.query(
            LearningActivity.resource_id, _sa_func.count(LearningActivity.id)
        ).filter(LearningActivity.resource_id.in_(res_ids)).group_by(
            LearningActivity.resource_id).all()
        act_counts = dict(act_rows)
        survey_rows = db.session.query(
            Survey.resource_id, _sa_func.count(Survey.id)
        ).filter(Survey.resource_id.in_(res_ids)).group_by(
            Survey.resource_id).all()
        survey_counts = dict(survey_rows)

    # 为每个资源读取文件列表
    import json as _json
    resource_data = []
    for res in resources_list:
        files = []
        is_external_link = False
        homework_count = 0
        activity_count = act_counts.get(res.id, 0)
        survey_count = survey_counts.get(res.id, 0)
        if res.url and (res.url.startswith('http://') or res.url.startswith('https://')):
            is_external_link = True
        # 文件列表由“浏览文件”按需加载，列表页不再扫描上传目录
        # 解析作业数量
        if res.homework_files:
            try:
                hw = _json.loads(res.homework_files)
                homework_count = len(hw) if isinstance(hw, list) else 0
            except Exception:
                homework_count = 0
        resource_data.append({
            'res': res, 'files': sorted(files, key=lambda x: x['name']),
            'is_external_link': is_external_link,
            'homework_count': homework_count,
            'activity_count': activity_count,
            'survey_count': survey_count
        })

    from app.blueprints.builtin_resources import suppressed_builtin_items
    audience_summaries = {}
    for rd in resource_data:
        if rd['res'].is_builtin:
            audience_summaries[rd['res'].id] = _audience_summary(
                _audience_rows(rd['res'].id))
    return render_template('admin_resources.html', resource_data=resource_data,
                           subjects=subjects, pagination=pagination,
                           audience_summaries=audience_summaries,
                           suppressed_builtins=suppressed_builtin_items())


@resources_bp.route('/admin/resources/toggle_vis/<int:res_id>', methods=['POST'])
@admin_login_required
def toggle_resource_visibility(res_id):
    """切换资源的 show_in_student / show_in_classroom"""
    res = db.get_or_404(Resource, res_id)
    flag = request.form.get('flag', '')
    value = request.form.get('value', '') == 'true'
    if flag in ('show_in_student', 'show_in_classroom'):
        setattr(res, flag, value)
        db.session.commit()
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        # 课件目录鉴权映射（_enforce_courseware_permissions 的唯一服务端防线，
        # dir_map TTL 300s）：不失效则刚被隐藏的资源直链最长 5 分钟仍可下载
        cache.delete('courseware:dir_map')
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '无效标志'}), 400


@resources_bp.route('/admin/resources/<int:res_id>/files')
@admin_login_required
def admin_resource_files(res_id):
    """管理端资源文件列表按“浏览文件”展开时加载，避免列表页扫描所有目录。"""
    res = db.get_or_404(Resource, res_id)
    dir_name = _resource_upload_dir(res)
    files = _upload_dir_snapshot(dir_name)['files'] if dir_name else []
    files = sorted(files, key=lambda x: x['name'])
    html = render_template('admin_resource_files.html', res=res, files=files)
    response = Response(
        '<div class="admin-files-fragment" data-file-count="%d">%s</div>'
        % (len(files), html), mimetype='text/html')
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@resources_bp.route('/admin/resources/upload_page')
@admin_login_required
def admin_resources_upload_page():
    subjects = get_subjects_cached()
    return render_template('admin_resources_upload.html', subjects=subjects)


@resources_bp.route('/teacher/resource-library')
@teacher_login_required
def teacher_resource_library():
    """教师资源库：编辑模式只看自己；只读模式看自己 + 被共享。"""
    is_admin = bool(session.get('is_admin'))
    teacher_id = session.get('teacher_id')
    mode = session.get('teacher_mode') or 'edit'
    resources = teacher_visible_resources(
        teacher_id, is_admin=is_admin, mode=mode).order_by(Resource.id.desc()).all()
    if teacher_id and not is_admin:
        # 课堂可用资源（本人创建/共享 + 管理员年级学科授权命中 + 旧公开）
        # 也补充列在资源库，仅课堂使用/目录入口，管理仍限管理员
        seen_ids = {r.id for r in resources}
        classroom_visible = teacher_visible_resources(
            teacher_id, is_admin=False, mode=mode, classroom=True).order_by(
                Resource.id.desc()).all()
        resources += [r for r in classroom_visible if r.id not in seen_ids]
    can_edit = {r.id: teacher_can_edit(r, teacher_id, is_admin) for r in resources}
    share_counts = {r.id: len(r.shared_teachers or []) for r in resources}
    activity_counts = {}
    survey_counts = {}
    if resources:
        from sqlalchemy import func as _sa_func
        rows = db.session.query(
            LearningActivity.resource_id, _sa_func.count(LearningActivity.id)
        ).filter(LearningActivity.resource_id.in_([r.id for r in resources])) \
            .group_by(LearningActivity.resource_id).all()
        activity_counts = dict(rows)
        survey_rows = db.session.query(
            Survey.resource_id, _sa_func.count(Survey.id)
        ).filter(Survey.resource_id.in_([r.id for r in resources])) \
            .group_by(Survey.resource_id).all()
        survey_counts = dict(survey_rows)
    return render_template(
        'teacher_resource_library.html', resources=resources,
        can_edit=can_edit, share_counts=share_counts,
        activity_counts=activity_counts, survey_counts=survey_counts,
        mode=mode,
        is_admin=is_admin,
        subjects=teacher_subjects(teacher_id) if teacher_id else get_subjects_cached())


@resources_bp.route('/teacher/resource-library/upload')
@teacher_edit_required
def teacher_resource_upload_page():
    """教师上传页：学科下拉只显示本人学科。"""
    return render_template('admin_resources_upload.html',
                           subjects=_available_subjects(), teacher_upload=True)


@resources_bp.route('/teacher/resource-library/add-link', methods=['POST'])
@teacher_edit_required
def teacher_resource_add_link():
    """教师编辑模式添加外部链接资源（仅限本人任教学科）。"""
    title = (request.form.get('title') or '').strip()
    url = (request.form.get('url') or '').strip()
    subject_id = parse_int(request.form.get('subject_id'))
    teacher_id = _session_teacher_id()
    if not title or not url:
        flash('资源标题和网址不能为空', 'danger')
        return redirect(url_for('resources.teacher_resource_library'))
    if not url.startswith(('http://', 'https://')):
        flash('外链资源仅支持 http(s) 网址', 'danger')
        return redirect(url_for('resources.teacher_resource_library'))
    if not teacher_id or not subject_id or not teacher_subject_allowed(
            teacher_id, subject_id):
        flash('请选择你所属的学科后再添加外链资源', 'danger')
        return redirect(url_for('resources.teacher_resource_library'))
    resource = Resource(
        title=title, url=url, subject_id=subject_id,
        creator_type='teacher', creator_teacher_id=teacher_id,
        creator_name=session.get('teacher_name') or '教师',
        show_in_student=True, show_in_classroom=True, quiz_mode='none')
    db.session.add(resource)
    db.session.add(Log(
        user_id=teacher_id, user_type='teacher', action='添加外链资源',
        detail=f'资源标题: {title}', time=datetime.now()))
    db.session.commit()
    cache.delete('study:resources:student')
    cache.delete('study:resources:classroom')
    flash('外链资源已添加', 'success')
    return redirect(url_for('resources.teacher_resource_library'))


@resources_bp.route('/teacher/resource-library/<int:res_id>/share', methods=['POST'])
@teacher_edit_required
def teacher_resource_share(res_id):
    """创建者/管理员按教师多选授权只读使用。"""
    res = db.get_or_404(Resource, res_id)
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        abort(403)
    ids = {int(x) for x in request.form.getlist('teacher_ids') if str(x).isdigit()}
    teachers = Teacher.query.filter(Teacher.id.in_(ids),
                                    Teacher.is_active.is_(True)).all() if ids else []
    # 创建者自己的资源不需要自共享
    if res.creator_teacher_id:
        teachers = [t for t in teachers if t.id != res.creator_teacher_id]
    res.shared_teachers = teachers
    db.session.add(Log(
        user_id=0, user_type='admin' if session.get('is_admin') else 'teacher',
        action='更新资源共享', detail=f'资源ID: {res.id}, 教师数: {len(teachers)}',
        time=datetime.now()))
    db.session.commit()
    _invalidate_study_caches(_resource_upload_dir(res))
    flash(f'已更新共享授权（{len(teachers)} 位教师只读可用）', 'success')
    return redirect(url_for('resources.edit_resource', res_id=res.id))


@resources_bp.route('/uploads/<filename>')
@admin_login_required
def uploaded_link(filename):
    """读取uploads下的链接文件并重定向到外链（仅管理员可访问）"""
    safe_name = (filename or '').replace('\\', '/').lstrip('/')
    if '..' in safe_name.split('/'):
        return '非法文件路径', 400
    base_dir = os.path.realpath(os.path.join(_BASE, 'uploads'))
    link_file = os.path.normpath(os.path.join(base_dir, safe_name))
    if link_file != base_dir and not link_file.startswith(base_dir + os.sep):
        return '非法文件路径', 400
    if not os.path.exists(link_file):
        return '链接不存在, 404', 404
    try:
        url = ""
        file_ext = filename.split('.')[-1].lower()
        if file_ext == 'url':
            with open(link_file, encoding='utf-8') as f:
                for line in f:
                    if line.startswith('URL='):
                        url = line[4:].strip()
                        break
            if not url:
                return '无效的URL文件格式', 400
        else:
            with open(link_file, encoding='utf-8') as f:
                url = f.read().strip()
        if not (url.startswith('http://') or url.startswith('https://')):
            url = 'http://' + url
        # 拒绝 javascript:/data: 等危险协议（防御以防模板被错误嵌入）
        if not (url.startswith('http://') or url.startswith('https://')):
            return '非法URL协议', 400
        return render_template('redirect.html', url=url, title="外部链接")
    except Exception as e:
        current_app.logger.error(f"访问外链失败: {str(e)}", exc_info=True)
        return '访问外链失败', 500


@resources_bp.route('/admin/resources/edit/<int:res_id>', methods=['GET', 'POST'])
@resources_bp.route('/teacher/resource-library/edit/<int:res_id>', methods=['GET', 'POST'])
@teacher_edit_required
def edit_resource(res_id):
    """编辑学习资源（管理员或资源创建者）"""
    import os as _os
    import json as _json
    res = db.session.get(Resource, res_id)
    if not res:
        flash('资源不存在')
        return redirect(url_for('resources.admin_resources'))
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        abort(403)
    if request.method == 'POST':
        res.title = request.form['title']
        sid = request.form.get('subject_id', '').strip()
        res.subject_id = int(sid) if sid else None
        teacher_editor = _session_teacher_id()
        if teacher_editor and (not res.subject_id or
                               not teacher_subject_allowed(teacher_editor, res.subject_id)):
            flash('请选择你所属的学科', 'danger')
            return redirect(url_for('resources.edit_resource', res_id=res_id))
        res.show_in_student = request.form.get('show_in_student') == '1'
        res.show_in_classroom = request.form.get('show_in_classroom') == '1'
        res.quiz_mode = request.form.get('quiz_mode', 'inject')
        # 公开资源仅管理员可改（全体教师课堂可见；教师创建的资源不能自设为公开）。
        # 内置资源的课堂呈现由「年级×学科授权」管理，旧 is_public 字段不再参与。
        if session.get('is_admin') and not res.is_builtin:
            res.is_public = request.form.get('is_public') == '1'

        is_file_resource = res.url and res.url.startswith('/static/uploads/')
        is_external = res.url and (res.url.startswith('http://') or res.url.startswith('https://'))
        if is_file_resource:
            res.allow_related_files = request.form.get(
                'allow_related_files') == '1'
        pending_inject = []

        if is_file_resource:
            url_path = res.url.replace('/static/uploads/', '', 1)
            dir_name = url_path.split('/')[0]
            dir_path = _os.path.join(_BASE, 'static', 'uploads', dir_name)

            # 删除标记的文件
            delete_list = request.form.getlist('delete_files')
            dir_path_real = _os.path.realpath(dir_path)
            for df in delete_list:
                safe_rel = (df or '').replace('\\', '/').lstrip('/')
                if '..' in safe_rel.split('/'):
                    continue
                target = _os.path.realpath(_os.path.join(dir_path_real, safe_rel))
                if target != dir_path_real and target.startswith(dir_path_real + _os.sep) and _os.path.isfile(target):
                    _os.remove(target)

            # 更新主页
            homepage = request.form.get('homepage', '').strip()
            remaining = []
            for root, _, filenames in _os.walk(dir_path):
                for fn in filenames:
                    if not fn.startswith('.'):
                        rel = _os.path.relpath(_os.path.join(root, fn), dir_path).replace('\\', '/')
                        # 课堂衍生文件（思维导图/PPTist 缓存）与备份不作为主页兜底
                        # （UI 文件卡片已过滤它们，指过去会导致资源无主页显示）
                        if rel.endswith('.pptist.json') or rel.endswith('.bak') or (
                                (rel.startswith('mindmap-') or rel.startswith('flow-')) and rel.endswith('.json')):
                            continue
                        remaining.append(rel)
            if remaining:
                if homepage and homepage in remaining:
                    res.url = f'/static/uploads/{dir_name}/{homepage}'
                else:
                    res.url = f'/static/uploads/{dir_name}/{remaining[0]}'

            # 更新作业和权限
            homework_list = request.form.getlist('homework_files')
            perm_dict = {}
            for rel in remaining:
                show_key = f'perm_show_{rel}'
                download_key = f'perm_download_{rel}'
                show_val = request.form.get(show_key) == '1'
                download_val = request.form.get(download_key) == '1'
                if rel not in homework_list:
                    perm_dict[rel] = {'show': show_val, 'download': download_val}
            res.homework_files = _json.dumps(homework_list, ensure_ascii=False)
            res.file_permissions = _json.dumps(perm_dict, ensure_ascii=False)

            if res.quiz_mode == 'inject':
                for fn in request.form.getlist('inject_files'):
                    if not fn or '..' in fn.replace('\\', '/').split('/'):
                        continue
                    if fn.lower().endswith(('.html', '.htm')) and fn in remaining:
                        pending_inject.append(fn)
                pending_inject = sorted(set(pending_inject))
            res.quiz_pending_files = (
                _json.dumps(pending_inject, ensure_ascii=False)
                if pending_inject else None)
            if pending_inject:
                res.quiz_inject_state = 'pending'
            else:
                res.quiz_inject_state = 'verified' if res.injected else 'none'
        elif is_external:
            new_url = request.form.get('url', '').strip()
            if new_url:
                res.url = new_url
            res.quiz_pending_files = None
            res.quiz_inject_state = 'verified' if res.injected else 'none'

        log = Log(
            user_id=0, user_type='admin',
            action='编辑学习资源',
            detail=f'资源ID: {res_id}, 新标题: {res.title}',
            time=datetime.now()
        )
        db.session.add(log)
        db.session.commit()
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        # 编辑可能改标题（dir_map 按标题建键）或改可见性：同步失效课件鉴权
        # 映射，否则隐藏/改名后直链鉴权最长滞后 5 分钟（与 API 编辑同口径）
        cache.delete('courseware:dir_map')
        # 编辑可能删除/重排文件，同步失效文件列表缓存
        if is_file_resource and dir_name:
            cache.delete(f'study:files:{dir_name}')
        if pending_inject:
            flash('资源已保存，请完成注入检测后应用采集脚本', 'info')
            return redirect(url_for('resources.resource_quiz_check', res_id=res.id))
        flash('修改成功')
        return redirect(
            url_for('resources.teacher_resource_library')
            if session.get('is_teacher') and not session.get('is_admin')
            else url_for('resources.admin_resources'))

    # GET: 读取文件列表
    files = []
    dir_name = ''
    homework_files = []
    file_perms = {}
    url_file = None
    if res.homework_files:
        try:
            homework_files = _json.loads(res.homework_files)
        except Exception:
            homework_files = []
    if res.file_permissions:
        try:
            file_perms = _json.loads(res.file_permissions)
        except Exception:
            file_perms = {}
    if res.url and res.url.startswith('/static/uploads/'):
        url_path = res.url.replace('/static/uploads/', '', 1)
        parts = url_path.split('/')
        if len(parts) >= 2:
            dir_name = parts[0]
            url_file = '/'.join(parts[1:])
            pending_set = set(_quiz_pending_files(res))
            snap = _upload_dir_snapshot(dir_name)
            collectors = _upload_dir_collectors(dir_name, snap)
            for entry in snap['files']:
                rel = entry['name']
                # 课堂页衍生文件（思维导图/PPTist 缓存）不出现在文件设置表
                if rel.endswith('.pptist.json') or (
                        (rel.startswith('mindmap-') or rel.startswith('flow-')) and rel.endswith('.json')):
                    continue
                perm = file_perms.get(rel, {})
                files.append({
                    'name': rel,
                    'ext': rel.rsplit('.', 1)[-1].lower() if '.' in rel else '',
                    'is_homepage': rel == url_file,
                    'is_homework': rel in homework_files,
                    'can_show': perm.get('show', True),
                    'can_download': perm.get('download', True),
                    'has_collector': collectors.get(rel, False),
                    'queued': rel in pending_set
                })
        files = sorted(files, key=lambda x: (not x.get('is_homepage', False), not x.get('is_homework', False), x['name']))

    # 课堂编排器文件选择通过 /admin/resources/<id>/lesson_files 按目录懒加载；
    # 不再把整份文件清单塞进页面（课件包文件多时会拖慢编辑页）。
    # 可挂载的互动活动（编排条目 kind=activity）与已发布问卷（kind=survey）
    lesson_activities = [{'id': a.id, 'title': a.title}
                         for a in LearningActivity.query.filter_by(
                             resource_id=res_id, is_active=True)
                         .order_by(LearningActivity.sort_order).all()]
    lesson_surveys = [{'id': s.id, 'title': s.title}
                      for s in Survey.query.filter_by(
                          resource_id=res_id, status='published')
                      .order_by(Survey.sort_order).all()]
    has_custom_tree = bool(res.lesson_tree)
    try:
        lesson_tree = _json.loads(res.lesson_tree) if res.lesson_tree else []
    except Exception:
        lesson_tree = []
    if not has_custom_tree:
        # 首次编排以系统默认树为起点：否则用户只添加一个新章节就保存，
        # 课堂页会认为"已有自定义编排"，原有主页/文件/活动全部消失。
        lesson_tree = _default_lesson_tree(
            files, lesson_activities, dir_name, surveys=lesson_surveys,
            external_url=(res.url if res.url and res.url.startswith(
                ('http://', 'https://')) else ''),
            external_title=res.title)
    subjects = _available_subjects()
    teacher_id = _session_teacher_id()
    can_share = teacher_can_edit(res, teacher_id, bool(session.get('is_admin')))
    shareable_teachers = []
    shared_teacher_ids = set()
    shareable_grades = []
    if can_share:
        query = Teacher.query.filter(Teacher.is_active.is_(True))
        if res.creator_teacher_id:
            query = query.filter(Teacher.id != res.creator_teacher_id)
        shareable_teachers = query.order_by(
            Teacher.display_name, Teacher.username).all()
        shared_teacher_ids = {t.id for t in (res.shared_teachers or [])}
        shareable_grades = sorted({
            (t.grade or '').strip() for t in shareable_teachers
            if (t.grade or '').strip()
        })
    audience_scope = None
    if session.get('is_admin') and res.is_builtin:
        audience_scope = _audience_scope_for_template(res)
    return render_template('edit_resource.html', res=res, subjects=subjects, files=files,
                           lesson_tree=lesson_tree,
                           lesson_tree_is_default=not has_custom_tree,
                           lesson_activities=lesson_activities,
                           lesson_surveys=lesson_surveys,
                           current_file=url_file,
                           can_share=can_share,
                           shareable_teachers=shareable_teachers,
                           shareable_grades=shareable_grades,
                           shared_teacher_ids=shared_teacher_ids,
                           audience_scope=audience_scope,
                           audience_grade_options=_teacher_grade_options(),
                           audience_subjects=get_subjects_cached())


# ── 内置资源：年级×学科授权（交集+通配） ──
_DEFAULT_TEACHER_GRADES = (
    '一年级', '二年级', '三年级', '四年级', '五年级', '六年级',
    '七年级', '八年级', '九年级',
    '初一', '初二', '初三', '高一', '高二', '高三',
)


def _teacher_grade_options():
    """授权年级候选：常见年级 + 教师档案中已使用的自定义年级。"""
    used = {(g or '').strip() for (g,) in db.session.query(Teacher.grade).filter(
        Teacher.grade.isnot(None), Teacher.grade != '').distinct().all()}
    options = list(_DEFAULT_TEACHER_GRADES)
    options += sorted(used - set(options))
    return options


def _audience_rows(res_id):
    return db.session.execute(resource_audience.select().where(
        resource_audience.c.resource_id == res_id)).fetchall()


def _audience_summary(rows):
    if not rows:
        return '未配置授权'
    all_grades = any(row.grade is None for row in rows)
    all_subjects = any(row.subject_id is None for row in rows)
    grades = sorted({row.grade for row in rows if row.grade})
    subject_ids = {row.subject_id for row in rows if row.subject_id}
    subjects = Subject.query.filter(Subject.id.in_(subject_ids)).all() \
        if subject_ids else []
    grade_text = '不限年级' if all_grades else '、'.join(grades)
    subject_text = '不限学科' if all_subjects else '、'.join(
        s.name for s in subjects)
    return f'{grade_text} × {subject_text}'


def _audience_scope_for_template(res):
    rows = _audience_rows(res.id)
    return {
        'all_grades': any(row.grade is None for row in rows) if rows else True,
        'all_subjects': any(row.subject_id is None for row in rows)
        if rows else True,
        'grades': sorted({row.grade for row in rows if row.grade}),
        'subject_ids': {row.subject_id for row in rows if row.subject_id},
        'summary': _audience_summary(rows),
        'builtin_label': getattr(res, 'builtin_key', '') or '',
    }


def _parse_audience_scope(form):
    """解析授权表单：返回 (grade_values, subject_values, error)。

    grade_values/subject_values 为 None 表示该维度不限（通配）。交集语义：
    年级与学科需同时命中；两项都「不限」= 全体教师可用。
    """
    all_grades = form.get('all_grades') == '1'
    all_subjects = form.get('all_subjects') == '1'
    grades = sorted({g.strip() for g in form.getlist('grades') if g.strip()})
    subject_ids = sorted({int(s) for s in form.getlist('subject_ids')
                          if str(s).isdigit()})
    if not all_grades and not grades:
        return None, None, '请选择年级，或勾选「不限年级」'
    if not all_subjects and not subject_ids:
        return None, None, '请选择学科，或勾选「不限学科」'
    if subject_ids:
        valid = {s.id for s in Subject.query.filter(
            Subject.id.in_(subject_ids)).all()}
        if valid != set(subject_ids):
            return None, None, '授权学科不存在（可能已被删除），请刷新后重试'
    grade_values = [None] if all_grades else grades
    subject_values = [None] if all_subjects else subject_ids
    return grade_values, subject_values, None


def _apply_audience_scope(res, grade_values, subject_values):
    db.session.execute(resource_audience.delete().where(
        resource_audience.c.resource_id == res.id))
    for grade in grade_values:
        for subject_id in subject_values:
            db.session.execute(resource_audience.insert().values(
                resource_id=res.id, grade=grade, subject_id=subject_id))


def _invalidate_audience_caches():
    """授权变更：失效资源列表与班级范围缓存（含 scope 版本号）。"""
    _invalidate_study_caches()
    cache.delete('courseware:dir_map')


@resources_bp.route('/admin/resources/<int:res_id>/audience', methods=['POST'])
@admin_login_required
def admin_resource_audience(res_id):
    """保存单个内置资源的年级×学科授权范围（管理员）。"""
    res = db.get_or_404(Resource, res_id)
    if not res.is_builtin:
        abort(400)
    grade_values, subject_values, error = _parse_audience_scope(request.form)
    if error:
        flash(error, 'danger')
        return redirect(url_for('resources.edit_resource', res_id=res_id))
    _apply_audience_scope(res, grade_values, subject_values)
    rows = _audience_rows(res.id)
    db.session.add(Log(
        user_id=0, user_type='admin', action='设置内置资源授权',
        detail=f'资源ID: {res.id}, 范围: {_audience_summary(rows)}',
        time=datetime.now()))
    db.session.commit()
    _invalidate_audience_caches()
    flash('授权范围已保存', 'success')
    return redirect(url_for('resources.edit_resource', res_id=res_id))


@resources_bp.route('/admin/resources/audience', methods=['GET', 'POST'])
@admin_login_required
def admin_resource_audience_batch():
    """内置资源批量授权页：按年级×学科一次授权多个内置资源。"""
    from app.blueprints.builtin_resources import suppressed_builtin_items
    builtins = Resource.query.filter_by(is_builtin=True).order_by(
        Resource.id).all()
    if request.method == 'POST':
        id_list = sorted({int(x) for x in request.form.getlist('resource_ids')
                          if str(x).isdigit()})
        selected = Resource.query.filter(
            Resource.id.in_(id_list), Resource.is_builtin.is_(True)).all() \
            if id_list else []
        grade_values, subject_values, error = _parse_audience_scope(
            request.form)
        if not selected:
            flash('请选择要授权的内容资源', 'danger')
        elif error:
            flash(error, 'danger')
        else:
            for res in selected:
                _apply_audience_scope(res, grade_values, subject_values)
            summary = _audience_summary(_audience_rows(selected[0].id))
            db.session.add(Log(
                user_id=0, user_type='admin', action='批量授权内置资源',
                detail=f'资源数: {len(selected)}, 范围: {summary}',
                time=datetime.now()))
            db.session.commit()
            _invalidate_audience_caches()
            flash(f'已批量授权 {len(selected)} 个内置资源：{summary}',
                  'success')
        return redirect(url_for('resources.admin_resource_audience_batch'))
    scopes = {res.id: _audience_scope_for_template(res) for res in builtins}
    return render_template('admin_resource_audience.html',
                           builtins=builtins, scopes=scopes,
                           suppressed=suppressed_builtin_items(),
                           grade_options=_teacher_grade_options(),
                           subjects=get_subjects_cached())


@resources_bp.route('/admin/builtin-resources/restore', methods=['POST'])
@admin_login_required
def admin_builtin_restore():
    """恢复被停用（墓碑）的内置资源（重新执行种子）。"""
    from app.blueprints.builtin_resources import (BUILTIN_LABELS,
                                                  restore_builtin)
    key = (request.form.get('key') or '').strip()
    if key not in BUILTIN_LABELS:
        abort(400)
    created = restore_builtin(key)
    _invalidate_audience_caches()
    flash('内置资源已恢复' if created else '内置资源已处于启用状态',
          'success')
    return redirect(url_for('resources.admin_resource_audience_batch'))


def _remove_activity_docs_dir(res_id):
    """删除资源的活动文档目录 activity_docs/<res_id>/（DB 提交成功后调用，尽力而为）。"""
    docs_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads', 'activity_docs'))
    ad_dir = os.path.realpath(os.path.join(docs_root, str(int(res_id))))
    try:
        if ad_dir.startswith(docs_root + os.sep) and os.path.isdir(ad_dir):
            shutil.rmtree(ad_dir)
    except OSError:
        current_app.logger.warning('删除资源活动文档目录失败（忽略）: %s', ad_dir)


def _delete_surveys_for_resources(resource_ids):
    """删除资源下问卷的全部答卷/题目/问卷行（bulk delete 不触发 ORM 级联）。

    survey.resource_id、survey_question.survey_id、survey_answer.survey_id 三处
    FK 均无 ON DELETE CASCADE；删除资源/学科时若不预先清理，任一问卷有答卷
    或题目就会 IntegrityError（删除 500）。
    """
    if not resource_ids:
        return
    survey_ids = [row[0] for row in db.session.query(Survey.id).filter(
        Survey.resource_id.in_(resource_ids)).all()]
    if not survey_ids:
        return
    SurveyAnswer.query.filter(SurveyAnswer.survey_id.in_(survey_ids)).delete(
        synchronize_session=False)
    SurveyQuestion.query.filter(
        SurveyQuestion.survey_id.in_(survey_ids)).delete(
        synchronize_session=False)
    Survey.query.filter(Survey.id.in_(survey_ids)).delete(
        synchronize_session=False)


@resources_bp.route('/admin/resources/delete/<int:res_id>', methods=['POST'])
@resources_bp.route('/teacher/resource-library/<int:res_id>/delete', methods=['POST'])
@teacher_edit_required
def delete_resource(res_id):
    """删除学习资源及其所有文件"""
    resource = db.get_or_404(Resource, res_id)
    if not teacher_can_edit(resource, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        abort(403)
    dir_name = None
    if resource.url and resource.url.startswith('/static/uploads/'):
        url_path = resource.url.replace('/static/uploads/', '', 1)
        parts = url_path.split('/')
        if len(parts) >= 1:
            dir_name = parts[0]
    rm_dir = dir_name if _resource_dir_deletable(dir_name, res_id) else None
    # 收集该资源下学习活动的作品磁盘路径（student_works/<aid>/<sid>/ 与
    # activity_docs/ 位于资源目录之外，ORM 级联删除数据行后磁盘文件会残留）
    from app.models import LearningActivity as _LA, StudentWork as _SW
    activity_ids = [a.id for a in _LA.query.filter_by(resource_id=res_id).all()]
    work_disk = []
    if activity_ids:
        work_disk += [w.file_path for w in _SW.query.filter(
            _SW.activity_id.in_(activity_ids)).all() if w.file_path]
    try:
        # 先清理引用该资源的子表记录（FK 无级联，不清理会在 commit 时抛 IntegrityError）：
        # 资源内嵌测验成绩 + 教师上课教学记录（resource_id 非空且无级联，只能删除）
        ResourceQuizResult.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
        quiz_analysis_cache.invalidate_analysis(res_id)
        TeachingSession.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
        # 问卷：survey.resource_id 与 survey_answer.survey_id 均无级联，
        # 答过卷的资源直接删除会在 commit 时 500；先删答卷/题目再删问卷
        _delete_surveys_for_resources([res_id])
        # 年级×学科授权范围（普通表关系，ORM 不识别的 FK 行）
        db.session.execute(resource_audience.delete().where(
            resource_audience.c.resource_id == res_id))
        # 内置资源删除 = 停用（墓碑）：重启种子不再复活，可在管理端恢复
        if resource.is_builtin and resource.builtin_key:
            SystemConfig.set(
                f'builtin_suppressed:{resource.builtin_key}', '1')
        db.session.delete(resource)
        log = Log(
            user_id=0, user_type='admin',
            action='删除学习资源',
            detail=f'资源标题: {resource.title}',
            time=datetime.now()
        )
        db.session.add(log)
        db.session.commit()
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        cache.delete('courseware:dir_map')   # 与 API 删除同口径：课件鉴权映射即时失效
        if dir_name:
            cache.delete(f'study:files:{dir_name}')
        flash('学习资源已删除')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除学习资源失败: res_id={res_id}, error={e}', exc_info=True)
        flash('删除学习资源失败', 'danger')
        return redirect(url_for('resources.teacher_resource_library')
                        if _session_teacher_id() else
                        url_for('resources.admin_resources'))
    # DB 提交成功后再删磁盘目录：磁盘删除失败仅残留孤儿文件（下次清理/不影响功能），
    # 避免"磁盘已删但 DB 删除失败"导致资源记录悬空指向不存在的文件
    if rm_dir:
        try:
            uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
            dir_path = os.path.realpath(os.path.join(uploads_root, rm_dir))
            if dir_path != uploads_root and dir_path.startswith(uploads_root + os.sep) \
                    and os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
        except OSError as e:
            current_app.logger.warning(f'删除资源磁盘目录失败（忽略，仅残留孤儿目录）: {dir_path}, error={e}')
    # 清理活动作品与活动文档磁盘文件（DB 已成功删除，尽力而为）
    if work_disk:
        try:
            from app.utils import delete_file_from_disk as _delete_file
            for rel in work_disk:
                try:
                    _delete_file(rel)
                except Exception:
                    pass
        except Exception:
            current_app.logger.warning('删除资源活动作品磁盘文件失败（忽略）', exc_info=True)
    for aid in activity_ids:
        try:
            works_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads', 'student_works'))
            aw_dir = os.path.realpath(os.path.join(works_root, str(aid)))
            if aw_dir != works_root and aw_dir.startswith(works_root + os.sep) \
                    and os.path.isdir(aw_dir):
                shutil.rmtree(aw_dir)
        except OSError:
            pass
    # 活动文档按**资源** id 存放（activities.py 写入 activity_docs/<res_id>/）。
    # 此前这里按活动 id 删 activity_docs/<aid>/：活动 id 恰等于另一资源 id 时
    # 会静默删掉那个资源的全部活动文档，本资源的文档反而残留
    _remove_activity_docs_dir(res_id)
    return redirect(url_for('resources.teacher_resource_library')
                    if _session_teacher_id() else
                    url_for('resources.admin_resources'))


@resources_bp.route('/admin/resources/delete-file/<int:res_id>', methods=['POST'])
@teacher_edit_required
def delete_resource_file(res_id):
    """删除资源中的单个文件"""
    resource = db.get_or_404(Resource, res_id)
    if not teacher_can_edit(resource, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        abort(403)
    filename = request.form.get('filename', '').strip()
    if not filename:
        flash('未指定文件', 'danger')
        return redirect(url_for('resources.edit_resource', res_id=res_id))

    if resource.url and resource.url.startswith('/static/uploads/'):
        url_path = resource.url.replace('/static/uploads/', '', 1)
        parts = url_path.split('/')
        if len(parts) >= 1:
            dir_name = parts[0]
            # 安全校验：文件必须在资源目录内
            import os as _os
            base = _os.path.join(_BASE, 'static', 'uploads', dir_name)
            base_real = _os.path.realpath(base)
            safe_name = (filename or '').replace('\\', '/').lstrip('/')
            if '..' in safe_name.split('/'):
                flash('非法文件路径', 'danger')
                return redirect(url_for('resources.edit_resource', res_id=res_id))
            target = _os.path.realpath(_os.path.join(base_real, safe_name))
            if target == base_real or not target.startswith(base_real + _os.sep):
                flash('非法文件路径', 'danger')
                return redirect(url_for('resources.edit_resource', res_id=res_id))
            if _os.path.exists(target) and _os.path.isfile(target):
                _os.remove(target)
                # 若删除的正是主页文件，res.url 会悬空指向不存在的文件：
                # 自动改指向剩余文件，无剩余文件则清空 URL
                # 注意：filename（表单 f.name）相对资源目录、无目录前缀；
                # res.url 去掉 /static/uploads/ 前缀后是 `<dir>/<file>`。
                # 此前拿二者直接比较（`<dir>/<file>` vs `<file>`）恒不成立，
                # 主页兜底分支从不执行——删掉主页文件后 res.url 成死链，
                # 需管理员手工重存设置才恢复。按带目录前缀的完整相对路径比较。
                url_path = resource.url.replace('/static/uploads/', '', 1).replace('\\', '/')
                if url_path == f'{dir_name}/{safe_name}':
                    remaining = []
                    if _os.path.isdir(base_real):
                        for root, _, filenames in _os.walk(base_real):
                            for fn in filenames:
                                if not fn.startswith('.'):
                                    rel = _os.path.relpath(
                                        _os.path.join(root, fn), base_real).replace('\\', '/')
                                    # 课堂衍生文件与备份不作为主页兜底
                                    if rel.endswith('.pptist.json') or rel.endswith('.bak') or (
                                            (rel.startswith('mindmap-') or rel.startswith('flow-')) and rel.endswith('.json')):
                                        continue
                                    remaining.append(rel)
                    if remaining:
                        remaining.sort()
                        resource.url = f'/static/uploads/{dir_name}/{remaining[0]}'
                    else:
                        resource.url = None
                    db.session.commit()
                    _invalidate_study_caches(dir_name)
                    flash(f'文件 "{filename}" 已删除，主页已自动切换到剩余文件', 'success')
                else:
                    # 非主页文件删除同样失效学习页/编辑页缓存：study:files:
                    # 与 study:resources:* 缓存了目录文件清单，不失效则
                    # /study 卡片与编辑页最长 5 分钟仍显示已删文件（死链）
                    _invalidate_study_caches(dir_name)
                    flash(f'文件 "{filename}" 已删除', 'success')
            else:
                flash('文件不存在', 'warning')

    return redirect(url_for('resources.edit_resource', res_id=res_id))


@resources_bp.route('/admin/resources/save_homepage', methods=['POST'])
@admin_login_required
def save_resource_homepage():
    """保存主页文件，更新数据库url字段"""
    try:
        data = request.get_json()
        title = data.get('title')
        homepage = data.get('homepage')
        if not title or not homepage:
            return jsonify({'success': False, 'msg': '参数缺失'}), 400
        # homepage 必须为纯文件名（无路径分隔符/连续点）：直接拼入 URL 落库
        # 后展示给学生，管理员被社工诱导填写 ../ 或 / 时可制造指向
        # 异常路径/站外的课件链接
        if '/' in homepage or '\\' in homepage or '..' in homepage.split('/')[-1] \
                or homepage.startswith('.'):
            return jsonify({'success': False, 'msg': '主页文件名不合法'}), 400
        homepage = secure_filename_with_unicode(homepage)
        safe_title = _resource_dir_name(title)
        if not homepage or not safe_title:
            return jsonify({'success': False, 'msg': '资源标题或主页文件名不合法'}), 400
        res = Resource.query.filter_by(title=title).order_by(Resource.id.desc()).first()
        if not res:
            res = Resource.query.filter_by(title=safe_title).order_by(Resource.id.desc()).first()
        if not res:
            resource_url = f'/static/uploads/{safe_title}/{homepage}'
            res = Resource(title=title, url=resource_url,
                           creator_type='admin',
                           creator_name=session.get('admin_name') or '管理员')
            db.session.add(res)
            db.session.commit()
            # 新建资源同样失效缓存：study:resources:* 缓存资源清单，
            # 不失效则 /study 最长 5 分钟看不到新资源
            _invalidate_study_caches(safe_title)
            return jsonify({'success': True, 'msg': '资源创建成功', 'resource_title': title})
        res.url = f'/static/uploads/{safe_title}/{homepage}'
        res.title = title
        db.session.commit()
        # 主页指向（res.url 决定卡片 is_homepage）已变更，双键失效
        _invalidate_study_caches(safe_title)
        return jsonify({'success': True, 'msg': '主页文件保存成功', 'resource_title': title})
    except Exception as e:
        current_app.logger.error(f"保存主页文件失败: {str(e)}")
        return jsonify({'success': False, 'msg': '保存主页文件失败'}), 500


@resources_bp.route('/study')
def study():
    """学习资源页面 — 支持课堂教学模式"""
    from flask import session
    # 课件公开开关（courseware_public_enabled，默认公开）：关闭后
    # /study 页面仅登录用户可访问，未登录重定向登录页
    from app.models import SystemConfig as _SC
    if not _SC.get_bool('courseware_public_enabled', True):
        if not (session.get('student_id') or session.get('is_admin')
                or session.get('is_teacher')):
            return redirect(url_for('auth.login'))
    classroom_mode = (request.args.get('mode') == 'classroom'
                      and bool(session.get('is_admin') or session.get('is_teacher')))
    is_admin = bool(session.get('is_admin'))
    teacher_id = session.get('teacher_id')
    teacher_mode = session.get('teacher_mode') or 'edit'
    student_id = session.get('student_id')
    student = None
    student_class_id = None
    if student_id:
        student = db.session.get(Student, student_id)
        student_class_id = student.class_id if student else None
    scope_sig = (classroom_scope_signature(student_class_id)
                 if student_id and not classroom_mode else None)
    if teacher_id and not is_admin:
        # 教师资源视图统一按创建/共享授权过滤；课堂模式额外要求课堂可见。
        resources_list = teacher_visible_resources(
            teacher_id, is_admin=False, mode=teacher_mode,
            classroom=classroom_mode).all()
        resource_data = _build_study_resource_data(resources_list, include_files=False)
    elif student_id:
        # 学生只看到「任课教师范围 + 公开/内置允许公开」的资源；没有
        # 任课教师时仅公开/内置资源（不再回退全局全量列表）。
        version = cache.get('study:resources:scope:version') or 0
        cache_key = (f'study:resources:student:scope:{scope_sig}:v{version}')
        resource_data = cache.get(cache_key)
        if resource_data is None:
            with _study_build_lock:
                resource_data = cache.get(cache_key)
                if resource_data is None:
                    scoped = student_classroom_scoped_resources(
                        student_class_id) or []
                    resource_data = _build_study_resource_data(scoped, include_files=False)
                    cache.set(cache_key, resource_data, timeout=30)
    else:
        cache_key = f'study:resources:{"classroom" if classroom_mode else "student"}'
        resource_data = cache.get(cache_key)
        if resource_data is None:
            # 重建锁（进程内双检）防缓存 stampede：250 人同时在线时避免
            # 缓存过期后所有请求同时触发全量重建
            with _study_build_lock:
                resource_data = cache.get(cache_key)
                if resource_data is None:
                    resources_list = Resource.query.all()
                    if classroom_mode:
                        resources_list = [r for r in resources_list if r.show_in_classroom]
                    else:
                        resources_list = [r for r in resources_list if r.show_in_student]
                    resource_data = _build_study_resource_data(resources_list, include_files=False)
                    cache.set(cache_key, resource_data, timeout=300)
    exams_total = Exam.query.filter_by(
        is_active=True, is_visible=True, is_enabled=True).count()
    # ── 学生「今日学习」聚合（V6.0）──
    # 待交作业/当前节次/可用试卷集中展示，让学生一进首页就知道下一步做什么。
    # 按学生缓存 60 秒：作业提交/创建会清理该键，避免每次刷新做 2 次查询。
    learning_summary = None
    if student_id and not classroom_mode:
        from app.models import (Homework as _HW, HomeworkSubmission as _HS,
                                ClassSchedule as _CS, Class as _Cls,
                                homework_classes as _hc)
        summary_key = f'learning:summary:{student_id}'
        learning_summary = cache.get(summary_key)
        if learning_summary is None:
            now = datetime.now()
            submitted = db.session.query(_HS.homework_id).filter(
                _HS.student_id == student_id)
            due = _HW.query.join(
                _hc, _hc.c.homework_id == _HW.id).filter(
                _hc.c.class_id == student_class_id,
                _HW.is_active.is_(True),
                ~_HW.id.in_(submitted),
                or_(_HW.deadline.is_(None), _HW.deadline >= now)).count()
            period = None
            if student and student.class_id:
                cls = db.session.get(_Cls, student.class_id)
                if cls:
                    current_time = now.strftime('%H:%M')
                    rows = _CS.query.filter_by(
                        class_name=cls.name,
                        weekday=now.isoweekday()).all()
                    period_numbers = {r.period_number for r in rows}
                    if period_numbers:
                        for idx, s in enumerate(get_schedules_cached(), 1):
                            if s.start_time <= current_time <= s.end_time:
                                if idx in period_numbers:
                                    period = {
                                        'name': s.period_name,
                                        'start': s.start_time,
                                        'end': s.end_time,
                                    }
                                break
            learning_summary = {
                'pending_homework': due,
                'exams_available': exams_total,
                'period': period,
            }
            cache.set(summary_key, learning_summary, timeout=60)

    results_count = 0
    avg_score = 0
    if student_id:
        from app.models import Result
        from sqlalchemy import func as _func, case as _case
        # 单行聚合替代全量加载：此前加载该生全部答卷（每行含 answers/scores
        # 大 Text JSON）只为算条数与平均分，考试次数越多首页越慢。
        # 「完成测试」计数含全部答卷（不泄露分值）；平均分仅覆盖「已公布成绩」
        # 的试卷——否则未公布卷也计入均值，学生用「已知已公布卷分数 + 总均分」
        # 即可反推未公布卷分值（与详情页/趋势/SPA 的 allow_view_results 门控一致）。
        row = db.session.query(
            _func.count(Result.id),
            _func.avg(_case((Exam.allow_view_results.is_(True),
                             Result.total_score)))
        ).outerjoin(Exam, Result.exam_id == Exam.id).filter(
            Result.student_id == student_id).first()
        results_count = row[0] or 0
        if results_count > 0 and row[1] is not None:
            avg_score = round(float(row[1]), 1)

    # 课堂模式：获取当前上课信息
    classroom_info = None
    class_buttons_enabled = True
    active_teaching_resource_ids = set()
    if classroom_mode:
        from app.models import (ClassroomSetting, ClassroomSession,
                                SystemConfig, TeachingSession)
        class_buttons_enabled = SystemConfig.get_bool('class_buttons_enabled', True)
        if session.get('is_admin') or session.get('is_teacher'):
            teacher_name = '管理员' if session.get('is_admin') else (session.get('teacher_name') or '教师')
            active_teaching_resource_ids = {
                row.resource_id for row in TeachingSession.query.filter_by(
                    teacher_name=teacher_name, end_time=None).all()
            }
        active_sessions = ClassroomSession.query.filter_by(is_active=True).all()
        chosen_session = None
        sid = session.get('student_id')
        if sid:
            student = db.session.get(Student, sid)
            if student:
                chosen_session = next((x for x in active_sessions
                                       if x.class_id == student.class_id), None)
        elif session.get('is_teacher') and not session.get('is_admin'):
            own_ids = teacher_class_ids(session.get('teacher_id'))
            chosen_session = next((x for x in active_sessions
                                   if x.class_id in own_ids), None)
        if chosen_session is None and active_sessions:
            chosen_session = active_sessions[0]
        cs = chosen_session or ClassroomSetting.query.first()
        if cs and cs.active_class:
            now = datetime.now()
            current_time = now.strftime('%H:%M')
            current_period = None
            schedules = get_schedules_cached()
            for s in schedules:
                if s.start_time <= current_time <= s.end_time:
                    current_period = s
                    break
            classroom_info = {
                'class_id': cs.active_class.id,
                'class_name': cs.active_class.name,
                'period': current_period.period_name if current_period else '课间休息',
                'time_range': f'{current_period.start_time}-{current_period.end_time}' if current_period else '',
                'message': cs.display_message or '',
                'schedules': [{
                    'period_name': x.period_name,
                    'start_time': x.start_time,
                    'end_time': x.end_time,
                    'is_current': (current_period is not None and x.id == current_period.id)
                } for x in schedules]
            }

    # 按学科分组 + 服务端分页：只渲染当前页资源卡片，避免 120+ 资源
    # 一次性进入 Jinja/DOM。搜索和学科筛选同样在服务端完成，保证跨页有效。
    if teacher_id and not is_admin:
        # 教师端分组 = 本人任教学科 ∪ 当前可见资源实际出现的学科：
        # 若只列任教学科，内置资源（如“仿真实验”分类的铜匠实验室）对未任教该科的
        # 教师会错误落入「未分类」，即使管理员已设置分类。
        own_subjects = teacher_subjects(teacher_id)
        own_ids = {s.id for s in own_subjects}
        visible_subject_ids = {
            rd['res'].get('subject_id') for rd in resource_data
            if rd['res'].get('subject_id')}
        if visible_subject_ids - own_ids:
            own_subjects = own_subjects + [
                s for s in get_subjects_cached()
                if s.id in visible_subject_ids and s.id not in own_ids]
        subjects_list = own_subjects
    elif scope_sig:
        # 学生端跟随上课教师时，只保留该范围内实际出现的学科分类，
        # 不展示其他学科的空分类。
        visible_subject_ids = {
            rd['res'].get('subject_id') for rd in resource_data
            if rd['res'].get('subject_id')}
        subjects_list = [s for s in get_subjects_cached()
                         if s.id in visible_subject_ids]
    else:
        subjects_list = get_subjects_cached()

    q = (request.args.get('q') or '').strip()[:100]
    subject_filter = (request.args.get('subject') or 'all').strip()
    if subject_filter not in ('all', 'none'):
        sid_filter = parse_int(subject_filter)
        subject_filter = str(sid_filter) if sid_filter is not None else 'all'
    q_lower = q.lower()
    filtered_data = []
    for rd in resource_data:
        title = str(rd['res'].get('title') or '').lower()
        if q_lower and q_lower not in title:
            continue
        sid = rd['res'].get('subject_id')
        if subject_filter == 'none' and sid is not None:
            continue
        if subject_filter not in ('all', 'none') and str(sid) != subject_filter:
            continue
        filtered_data.append(rd)

    total_resources = len(filtered_data)
    total_files_count = sum(len(rd.get('files') or []) for rd in resource_data)
    per_page = 12
    page = max(1, parse_int(request.args.get('page'), 1) or 1)
    pages = max(1, (total_resources + per_page - 1) // per_page)
    if page > pages:
        page = pages
    page_start = (page - 1) * per_page
    page_data = filtered_data[page_start:page_start + per_page]

    subject_counts = {}
    for rd in filtered_data:
        key = str(rd['res'].get('subject_id') or 'none')
        subject_counts[key] = subject_counts.get(key, 0) + 1

    grouped = {}  # subject_id -> {subject, resources: []}
    grouped[None] = {'subject': None, 'resources': []}
    for s in subjects_list:
        grouped[s.id] = {'subject': s, 'resources': []}
    for rd in page_data:
        sid = _resource_subject_id(rd)
        if sid in grouped:
            grouped[sid]['resources'].append(rd)
        else:
            grouped[None]['resources'].append(rd)
    grouped_list = [g for g in grouped.values() if g['resources']]

    def _study_url(subject='all', page_no=1, q_val=None):
        url_args = {'page': page_no}
        if classroom_mode:
            url_args['mode'] = 'classroom'
        if q_val:
            url_args['q'] = q_val
        if subject and subject != 'all':
            url_args['subject'] = subject
        return url_for('resources.study', **url_args)

    subject_urls = {'all': _study_url('all', 1, q), 'none': _study_url('none', 1, q)}
    for s in subjects_list:
        subject_urls[str(s.id)] = _study_url(str(s.id), 1, q)
    page_urls = {p: _study_url(subject_filter, p, q) for p in range(1, pages + 1)}
    clear_url = _study_url('all', 1, '')
    # 仅清搜索词、保留当前学科/课堂模式（搜索框旁的 ✕ 只负责搜索）
    clear_search_url = _study_url(subject_filter, 1, '')

    # 学生已答问卷（单条 IN 查询；不进入共享资源缓存结构，随页面实时呈现）
    answered_survey_ids = set()
    if student_id:
        answered_survey_ids = {row[0] for row in db.session.query(
            SurveyAnswer.survey_id).filter(
            SurveyAnswer.student_id == student_id).all()}

    return render_template('study.html',
                           grouped_resources=grouped_list,
                           results_count=results_count,
                           avg_score=avg_score,
                           exams_total=exams_total,
                            learning_summary=learning_summary,
                            classroom_mode=classroom_mode,
                            classroom_info=classroom_info,
                            class_buttons_enabled=class_buttons_enabled,
                            active_teaching_resource_ids=active_teaching_resource_ids,
                            subjects=subjects_list,
                            resource_q=q,
                            current_subject=subject_filter,
                            subject_counts=subject_counts,
                            total_resources=total_resources,
                            total_files_count=total_files_count,
                            answered_survey_ids=answered_survey_ids,
                            page_info={'page': page, 'pages': pages,
                                       'total': total_resources,
                                       'per_page': per_page},
                            subject_urls=subject_urls,
                            page_urls=page_urls,
                            clear_url=clear_url,
                            clear_search_url=clear_search_url)


# ════════════════════════════════════════════════════════════════
# 课堂页（在线课堂式资源学习界面 /study/lesson/<id>）
#   - 章节树存 Resource.lesson_tree（JSON Text，沿用 homework_files 惯例）
#   - 服务端按角色过滤章节树：学生端不返回 visible.student=false 的条目
#   - 文件条目继续走 /static/uploads/ 课件目录鉴权（before_request 兜底）
# ════════════════════════════════════════════════════════════════

# 思维导图 / 流程拓扑图画板存于课件目录内的命名前缀（/study 文件卡片与默认
# 章节生成时过滤，不污染既有文件列表）
MINDMAP_PREFIX = 'mindmap-'
FLOW_PREFIX = 'flow-'
_MINDMAP_NAME_RE = re.compile(r'^mindmap-[A-Za-z0-9_\-一-龥]{1,80}\.json$')
_TOOL_DOC_PREFIXES = {'mindmap': MINDMAP_PREFIX, 'flow': FLOW_PREFIX}
_TOOL_DOC_NAME_RE = re.compile(r'^(?:mindmap|flow)-[A-Za-z0-9_\-一-龥]{1,80}\.json$')
_LESSON_KINDS = ('video', 'pptx', 'doc', 'geogebra', 'activity',
                 'survey', 'link')
_DOC_CATEGORIES = ('activity_sheet', 'guide', 'design', 'handout',
                   'exercise', 'answer', 'material', 'other')
_VIDEO_EXTS = {'mp4', 'webm', 'ogv', 'm4v', 'mov', 'avi', 'mkv',
               'mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'opus',
               'weba', 'aiff', 'aif'}
_PPT_EXTS = {'pptx', 'ppt'}

# 电子文档：预览能力分三档——JitViewer 直接预览、图片 / 其他媒体由前端
# 原生展示、其余格式仍可选择但课堂页回退为下载。注意：document_preview.html
# 的 jitSupported 是更宽的预览白名单（活动/作业/网盘入口还覆盖 PPTX/CAD/3D），
# 与本课堂分类清单不再逐项相等；两处同步时以各自用途为准。
_DOC_PREVIEW_EXTS = {
    'pdf', 'docx', 'xlsx', 'xls', 'ofd', 'txt', 'md', 'markdown', 'csv', 'tsv',
    'json', 'jsonc', 'yaml', 'yml',
    'py', 'js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx', 'css', 'scss', 'sass',
    'less', 'styl', 'cs', 'java', 'kt', 'kts', 'go', 'rs', 'c', 'cc', 'cpp',
    'cxx', 'h', 'hpp', 'hh', 'hxx', 'rb', 'php', 'swift', 'sql', 'sh',
    'bash', 'zsh', 'env', 'ini', 'conf', 'toml', 'vue',
}
_DOC_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'}
_DOC_DOWNLOAD_EXTS = {
    'doc', 'rtf', 'odt', 'ods', 'odp', 'wps', 'et', 'dps', 'docm', 'xlsm',
    'pptm', 'epub', 'mobi', 'azw3', 'tex', 'djvu', 'xps', 'pages', 'numbers',
    'key', 'tiff', 'tif', 'ico', 'log', 'xml',
}
_DOC_EXTS = _DOC_PREVIEW_EXTS | _DOC_IMAGE_EXTS | _DOC_DOWNLOAD_EXTS


def _lesson_file_kind(ext):
    """资源文件扩展名 → 编排条目类型（音频归入 video，沿用课堂播放器）。"""
    ext = (ext or '').lower()
    if ext in _VIDEO_EXTS:
        return 'video'
    if ext in _PPT_EXTS:
        return 'pptx'
    if ext in ('html', 'htm'):
        return 'link'
    if ext == 'ggb':
        return 'geogebra'
    if ext in _DOC_EXTS:
        return 'doc'
    return 'other'


def _lesson_doc_previewable(ext):
    """电子文档是否可在线预览；false 表示仍可加入编排但课堂页回退下载。"""
    return (ext or '').lower() in (_DOC_PREVIEW_EXTS | _DOC_IMAGE_EXTS)


_MINDMAP_MAX_BYTES = 2 * 1024 * 1024


def _lesson_node_id():
    return uuid.uuid4().hex[:12]


def _resource_upload_dir(res):
    """资源对应课件目录名（URL 首段）；外链资源返回 None"""
    url = res.url or ''
    if url.startswith('/static/uploads/'):
        parts = url[len('/static/uploads/'):].split('/')
        if parts and parts[0]:
            return parts[0]
    return None


def _invalidate_study_caches(dir_name=None):
    """资源/文件写路径统一失效缓存：目录文件清单（study:files:<dir>）与
    /study 资源聚合（study:resources:*），两份缓存 TTL 均为 300s。
    同时失效课件鉴权映射 courseware:dir_map（TTL 300s）：上传/设置向导会
    更新 show_in_student / file_permissions，漏删会让隐藏资源/文件直链在
    最长 5 分钟内仍可访问（此前仅 toggle/edit/delete 三处单独删除）。"""
    if dir_name:
        cache.delete(f'study:files:{dir_name}')
    cache.delete('study:resources:student')
    cache.delete('study:resources:classroom')
    cache.set('study:resources:scope:version', time.time_ns(), timeout=86400)
    cache.delete('courseware:dir_map')


def _sanitize_lesson_tree(data, dir_name=''):
    """校验并规范化课堂编排树（白名单字段 + 路径安全）。返回 (tree, err)"""
    if not isinstance(data, list) or not data:
        return None, '章节树不能为空'

    def _safe_node_id(raw):
        # id 用于前端 querySelector 高亮：白名单字符集，防注入选择器与
        # 重复 id 导致的高亮错位；不满足则重新生成
        raw = str(raw or '').strip()
        return raw if re.match(r'^[A-Za-z0-9_-]{1,64}$', raw) else _lesson_node_id()

    def clean_section(node, depth):
        if depth > 3:
            return None, '章节嵌套层级过深（最多 3 层）'
        if not isinstance(node, dict):
            return None, '章节节点格式错误'
        title = str(node.get('title') or '').strip()[:100]
        if not title:
            return None, '章节标题不能为空'
        children_in = node.get('children') if isinstance(node.get('children'), list) else []
        items_in = node.get('items') if isinstance(node.get('items'), list) else []
        if len(children_in) + len(items_in) > 100:
            return None, '单章节子节点过多'
        clean = {'id': _safe_node_id(node.get('id')),
                 'title': title, 'type': 'section',
                 'children': [], 'items': []}
        for ch in children_in[:100]:
            c, err = clean_section(ch, depth + 1)
            if err:
                return None, err
            clean['children'].append(c)
        for it in items_in[:100]:
            if not isinstance(it, dict):
                return None, '条目格式错误'
            it_title = str(it.get('title') or '').strip()[:100]
            kind = it.get('kind')
            if not it_title or kind not in _LESSON_KINDS:
                return None, f'条目「{it_title}」缺少标题或类型不合法'
            src = str(it.get('src') or '').strip()
            if kind in ('video', 'pptx', 'doc', 'geogebra'):
                # 课件目录内相对路径：禁绝对路径 / 目录穿越
                src = src.replace('\\', '/')
                if (not src or src.startswith('/') or '..' in src.split('/')
                        or '\x00' in src):
                    return None, f'条目「{it_title}」文件路径不合法'
                if kind == 'geogebra' and not src.lower().endswith('.ggb'):
                    return None, f'条目「{it_title}」必须是 .ggb 课件'
            elif kind == 'link':
                if not (src.startswith('http://') or src.startswith('https://')
                        or (src.startswith('/') and not src.startswith('//'))):
                    # 课件相对路径（html/htm 课件）：校验后规范化为站内绝对
                    # 路径，否则课堂页 iframe 会以课堂页 URL 为基准解析 → 404
                    src = src.replace('\\', '/')
                    if (not src or '..' in src.split('/') or '\x00' in src
                            or not dir_name):
                        return None, f'条目「{it_title}」链接不合法'
                    src = f'/static/uploads/{dir_name}/{src}'
            else:  # activity
                src = ''
            item = {'id': _safe_node_id(it.get('id')),
                    'title': it_title, 'kind': kind, 'src': src}
            if kind == 'link' and it.get('purpose') == 'quickform_results':
                from urllib.parse import urlparse as _urlparse
                parsed_src = _urlparse(src)
                if (parsed_src.scheme not in ('http', 'https')
                        or not parsed_src.netloc):
                    return None, f'条目「{it_title}」的 QuickForm 地址不合法'
                item['purpose'] = 'quickform_results'
                item['open_mode'] = ('embed' if it.get('open_mode') == 'embed'
                                     else 'newtab')
            if kind == 'doc':
                item['doc_category'] = (it.get('doc_category')
                                        if it.get('doc_category') in _DOC_CATEGORIES
                                        else 'guide')
            if kind == 'activity':
                try:
                    item['activity_id'] = int(it.get('activity_id') or 0)
                except (TypeError, ValueError):
                    item['activity_id'] = 0
            vis = it.get('visible') if isinstance(it.get('visible'), dict) else {}
            item['visible'] = {'teacher': vis.get('teacher', True) is not False,
                               'student': vis.get('student', True) is not False}
            clean['items'].append(item)
        return clean, None

    out = []
    for node in data[:60]:
        c, err = clean_section(node, 1)
        if err:
            return None, err
        out.append(c)
    return out, None


def _filter_lesson_tree(tree, is_teacher):
    """按角色过滤章节树：学生端剔除 visible.student=false 的条目及空章节。
    服务端过滤（学生收不到隐藏节点），而非前端隐藏。"""
    def filt(node):
        items = [it for it in node.get('items', [])
                 if is_teacher or (it.get('visible') or {}).get('student', True)]
        children = [c for c in (filt(ch) for ch in node.get('children', [])) if c]
        if not items and not children:
            return None
        out = dict(node)
        out['items'] = items
        out['children'] = children
        return out
    return [c for c in (filt(n) for n in (tree or [])) if c]


def _lesson_resource_accessible(res, is_teacher):
    """课堂页/课堂条目文件的统一资源级访问校验。

    学生按「任课教师范围 + 公开/内置」；教师按可见/课堂授权。管理员恒真。
    与 study_lesson 原内联判断保持同一口径，供条目文件路由复用。
    """
    if not is_teacher:
        sid = session.get('student_id')
        if sid:
            student = db.session.get(Student, sid)
            return bool(student_can_access_resource(res, student))
        return bool(res.show_in_student and
                    SystemConfig.get_bool('courseware_public_enabled', True))
    if session.get('is_teacher') and not session.get('is_admin'):
        mode = session.get('teacher_mode') or 'edit'
        public_ok = bool(res.show_in_classroom and
                         teacher_can_use_resource(res,
                                                  session.get('teacher_id')))
        return bool(public_ok or teacher_can_view(
            res, session.get('teacher_id'), is_admin=False, mode=mode))
    return True


def _find_lesson_item(res, item_id, is_teacher):
    """在资源自定义章节树中查找可播放的条目（含角色可见性校验）。

    仅自定义树（lesson_tree 非空）允许通过条目 id 定位：默认树的条目 id
    每次渲染随机生成，无法跨请求复用。活动/问卷条目没有文件，返回 None。
    """
    if not res.lesson_tree:
        return None
    try:
        tree = _json.loads(res.lesson_tree)
    except Exception:
        return None
    want = str(item_id or '')
    found = None

    def walk(nodes):
        nonlocal found
        if found is not None:
            return
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            for it in node.get('items') or []:
                if not isinstance(it, dict):
                    continue
                if str(it.get('id') or '') != want:
                    continue
                if it.get('kind') not in ('video', 'pptx', 'doc',
                                          'geogebra', 'link'):
                    return
                vis = it.get('visible') if isinstance(it.get('visible'), dict) else {}
                if not is_teacher and vis.get('student', True) is False:
                    return
                if is_teacher and not (session.get('is_admin')
                                       or vis.get('teacher', True) is not False):
                    return
                found = it
                return
            walk(node.get('children'))

    walk(tree if isinstance(tree, list) else [])
    return found


def _lesson_item_abs_path(res, item):
    """把章节条目 src 解析为资源课件目录内的真实文件路径（越界返回 None）。"""
    dir_name = _resource_upload_dir(res)
    if not dir_name or not _resource_dir_name(dir_name) or not item:
        return None
    src = str(item.get('src') or '').strip().replace('\\', '/')
    if not src or '\x00' in src:
        return None
    prefix = f'/static/uploads/{dir_name}/'
    if src.startswith('/static/uploads/'):
        if not src.lower().startswith(prefix.lower()):
            return None
        rel = src[len(prefix):]
    elif src.startswith('/'):
        return None
    else:
        rel = src
    if not rel or '..' in rel.split('/'):
        return None
    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    root = os.path.realpath(os.path.join(uploads_root, dir_name))
    if not os.path.normcase(root).startswith(os.path.normcase(uploads_root) + os.sep):
        return None
    abs_path = os.path.realpath(os.path.join(root, rel))
    if (os.path.normcase(abs_path) != os.path.normcase(root)
            and not os.path.normcase(abs_path).startswith(
                os.path.normcase(root) + os.sep)):
        return None
    return abs_path


def _default_lesson_tree(files, activities, dir_name='', surveys=None,
                         external_url='', external_title=''):
    """未编排（lesson_tree 为空）时按文件清单生成默认章节。
    文档分类用文件名启发式（教学设计→仅教师可见），可在编排面板调整。
    外链资源没有本地文件，用 external_url 生成一个课堂条目。"""
    node = {'id': _lesson_node_id(), 'title': '课程内容', 'type': 'section',
            'children': [], 'items': []}
    if external_url:
        node['items'].append({
            'id': _lesson_node_id(),
            'title': external_title or '外部资源',
            'kind': 'link', 'src': external_url,
            'visible': {'teacher': True, 'student': True},
        })
    for f in files:
        rel, ext = f.get('name', ''), f.get('ext', '')
        if not f.get('can_show', True):
            continue
        # 课堂页衍生文件双保险（上游 _build_study_resource_data 已剔除）
        if rel.endswith('.pptist.json') or (
                (rel.startswith(MINDMAP_PREFIX) or rel.startswith(FLOW_PREFIX)) and rel.endswith('.json')):
            continue
        if ext in _VIDEO_EXTS:
            kind = 'video'
        elif ext in _PPT_EXTS:
            kind = 'pptx'
        elif ext in _DOC_EXTS:
            kind = 'doc'
        elif ext == 'ggb':
            kind = 'geogebra'
        elif ext in ('html', 'htm'):
            kind = 'link'
        else:
            continue
        # html 课件走站内绝对路径（相对路径在课堂页 iframe 中会 404）
        item_src = (f'/static/uploads/{dir_name}/{rel}' if kind == 'link'
                    else rel)
        item = {'id': _lesson_node_id(),
                'title': rel.rsplit('/', 1)[-1].rsplit('.', 1)[0] or rel,
                'kind': kind, 'src': item_src}
        if kind == 'doc':
            if '教学设计' in rel:
                cat, vis = 'design', False
            elif '导学案' in rel:
                cat, vis = 'guide', True
            elif '活动' in rel:
                cat, vis = 'activity_sheet', True
            elif '教材分析' in rel or '讲义' in rel:
                cat, vis = 'handout', True
            elif '习题' in rel or '练习' in rel or '作业' in rel:
                cat, vis = 'exercise', True
            elif '答案' in rel or '参考' in rel:
                cat, vis = 'answer', True
            elif '素材' in rel:
                cat, vis = 'material', True
            else:
                cat, vis = 'other', True
            item['doc_category'] = cat
            item['visible'] = {'teacher': True, 'student': vis}
        node['items'].append(item)
    for a in activities or []:
        node['items'].append({'id': _lesson_node_id(), 'title': a['title'],
                              'kind': 'activity', 'src': '',
                              'activity_id': a['id'],
                              'visible': {'teacher': True, 'student': True}})
    for s in surveys or []:
        node['items'].append({'id': _lesson_node_id(), 'title': s['title'],
                              'kind': 'survey', 'src': '',
                              'survey_id': s['id'],
                              'visible': {'teacher': True, 'student': True}})
    return [node] if node['items'] else []


def _attach_activity_urls(tree):
    """为 activity/survey 条目补学生端入口 URL（/study/activity/<id>、/study/survey/<id>）"""
    def walk(node):
        for it in node.get('items', []):
            if it.get('kind') == 'activity' and it.get('activity_id'):
                it['url'] = f'/study/activity/{it["activity_id"]}'
            elif it.get('kind') == 'survey' and it.get('survey_id'):
                it['url'] = f'/study/survey/{it["survey_id"]}'
        for ch in node.get('children', []):
            walk(ch)
    for n in tree or []:
        walk(n)
    return tree


def _embed_internal_lab_links(tree):
    """课堂页舞台 iframe 内嵌的化学仿真页追加 embed=1。

    embed=1 由 base.html 处理：隐藏站点导航/页脚、跳过心跳与 AI 助手脚本，
    避免 iframe 内再套一层本站壳并出现重复的 AI 悬浮按钮（页内链接也会
    带上该参数）。仅改请求期渲染结果，不改库内章节树。
    """
    def walk(node):
        for it in node.get('items', []):
            src = it.get('src') or ''
            if it.get('kind') == 'link' and src.startswith('/chem-lab') \
                    and 'embed=1' not in src:
                it['src'] = src + ('&' if '?' in src else '?') + 'embed=1'
        for ch in node.get('children', []):
            walk(ch)
    for n in tree or []:
        walk(n)
    return tree


def _attach_geogebra_urls(tree, res_id):
    """为 geogebra 条目补播放器 URL（课堂舞台内嵌用 embed=1 极简壳）。

    文件相对路径（如 sub/demo.ggb）原样传给播放器路由，由其校验目录穿越
    与访问权限；不改库内章节树。
    """
    def walk(node):
        for it in node.get('items', []):
            if it.get('kind') == 'geogebra' and it.get('src'):
                it['player_url'] = url_for(
                    'resources.geogebra_player', res_id=res_id,
                    file=it['src'], embed=1)
        for ch in node.get('children', []):
            walk(ch)
    for n in tree or []:
        walk(n)
    return tree


@resources_bp.route('/study/lesson/<int:resource_id>')
def study_lesson(resource_id):
    """在线课堂式资源学习页面（学生/教师共用，?mode=classroom 为教师课堂模式）"""
    res = db.session.get(Resource, resource_id)
    if not res:
        abort(404)
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    classroom_mode = request.args.get('mode') == 'classroom' and is_teacher
    # 未登录：与 /study 一致受课件公开开关约束
    if not (session.get('student_id') or is_teacher):
        from app.models import SystemConfig as _SC
        if not _SC.get_bool('courseware_public_enabled', True):
            return redirect(url_for('auth.login'))
    # 可见性：学生按「任课教师范围 + 公开/内置」校验（课堂展示的隐藏
    # 资源也对学生可用）；未登录访客沿用 show_in_student。
    if not _lesson_resource_accessible(res, is_teacher):
        abort(404)
    if classroom_mode and is_teacher and not res.show_in_classroom:
        flash('该资源不在教师课堂端展示')
        return redirect(url_for('resources.study', mode='classroom'))

    data = _build_study_resource_data([res])[0]
    try:
        tree = _json.loads(res.lesson_tree) if res.lesson_tree else None
    except Exception:
        current_app.logger.warning('课堂章节树解析失败: res_id=%s', resource_id,
                                   exc_info=True)
        tree = None
    if not isinstance(tree, list):
        # 手工改库存成 dict 等非法结构时回退默认树，防下游迭代 500
        tree = None
    if not tree:
        tree = _default_lesson_tree(
            data['files'], data['activities'],
            _resource_upload_dir(res) or '',
            surveys=data.get('surveys') or [],
            external_url=(res.url if res.url and res.url.startswith(
                ('http://', 'https://')) else ''),
            external_title=res.title)
    tree = _attach_activity_urls(_filter_lesson_tree(tree, is_teacher))
    # 舞台内嵌的化学仿真页使用极简壳（无站点导航/页脚/AI 助手）
    tree = _embed_internal_lab_links(tree)
    # .ggb 条目补播放器 URL（课堂舞台 iframe 内嵌 GeoGebra）
    tree = _attach_geogebra_urls(tree, res.id)

    # 教师课堂上下文：是否已上课（决定"下课"按钮状态）
    in_class = False
    lesson_class_id = None
    if classroom_mode and is_teacher:
        from app.models import ClassroomSession
        requested_class = parse_int(request.args.get('class_id'))
        if session.get('is_admin'):
            if requested_class:
                lesson_class_id = requested_class
            else:
                active = ClassroomSession.query.filter_by(
                    is_active=True).order_by(ClassroomSession.id).first()
                lesson_class_id = active.class_id if active else None
        else:
            own_class_ids = teacher_class_ids(session.get('teacher_id'))
            if requested_class in own_class_ids:
                lesson_class_id = requested_class
            else:
                active = ClassroomSession.query.filter_by(
                    is_active=True).filter(
                        ClassroomSession.class_id.in_(own_class_ids)).order_by(
                            ClassroomSession.id).first() if own_class_ids else None
                lesson_class_id = active.class_id if active else None
        from app.blueprints.teaching import _current_teacher
        teacher_id, teacher_name = _current_teacher()
        q = TeachingSession.query.filter_by(resource_id=resource_id, end_time=None)
        if lesson_class_id:
            q = q.filter_by(class_id=lesson_class_id)
        rec = ((q.filter_by(teacher_id=teacher_id).order_by(
                    TeachingSession.start_time.desc()).first()
                if teacher_id
                else q.filter_by(teacher_name=teacher_name).order_by(
                    TeachingSession.start_time.desc()).first()))
        in_class = rec is not None

    return render_template('study_lesson.html',
                           res=res,
                           dir_name=_resource_upload_dir(res) or '',
                           lesson_tree=tree,
                           lesson_tree_exists=bool(res.lesson_tree),
                           is_teacher=is_teacher,
                           classroom_mode=classroom_mode,
                           in_class=in_class,
                           lesson_class_id=lesson_class_id)


@resources_bp.route('/study/resource/<int:resource_id>/files')
def study_resource_files(resource_id):
    """资源卡展开时按需加载文件网格（避免 /study 首屏扫描所有课件目录）。"""
    res = db.get_or_404(Resource, resource_id)
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not _lesson_resource_accessible(res, is_teacher):
        abort(404)
    rd = _build_study_resource_data([res])[0]
    html = render_template(
        'study_resource_files.html', res=rd['res'], rd=rd,
        files=rd['files'], homework=rd['homework_files'],
        visible=rd['visible_files'])
    response = Response(
        '<div class="study-files-fragment" data-file-count="%d">%s</div>'
        % (len(rd['files']), html), mimetype='text/html')
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@resources_bp.route('/study/lesson/<int:resource_id>/item/<item_id>/file')
def lesson_item_file(resource_id, item_id):
    """课堂章节条目文件（PDF/图片/视频/PPTX/HTML 课件）。

    章节树是教师在课堂编排里显式设定的学生可见范围：条目
    visible.student=true 时，即使文件级「展示」为 false，也应能在课堂内
    播放（否则勾选学生可见后点击 PDF 仍被预览/静态鉴权拦截）。
    直链仍受文件级权限约束——只有本路由在「条目存在且对学生可见」时放行，
    且路径只能落在该资源自己的课件目录内。
    """
    from flask import send_file
    res = db.get_or_404(Resource, resource_id)
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not _lesson_resource_accessible(res, is_teacher):
        abort(404)
    item = _find_lesson_item(res, item_id, is_teacher)
    if not item:
        abort(404)
    abs_path = _lesson_item_abs_path(res, item)
    if not abs_path or not os.path.isfile(abs_path):
        abort(404)
    if abs_path.lower().endswith(('.html', '.htm')):
        # /item/<id>/file 丢失原目录层级，HTML 的相对链接/脚本会请求到
        # /item/<id>/next.html。转到保留路径的课堂入口，不修改课件内容。
        root = os.path.realpath(os.path.join(
            _BASE, 'static', 'uploads', _resource_upload_dir(res)))
        rel = os.path.relpath(abs_path, root).replace('\\', '/')
        resp = redirect(url_for('resources.lesson_item_content',
                                resource_id=res.id, item_id=item_id,
                                filename=rel))
    else:
        resp = send_file(abs_path, conditional=True)
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


def _lesson_tree_allows_file(res, abs_path):
    """仅显式对学生可见的编排条目，可覆盖该文件自身的隐藏开关。"""
    try:
        tree = _json.loads(res.lesson_tree or '[]')
    except (TypeError, ValueError):
        return False

    def walk(nodes):
        if not isinstance(nodes, list):
            return False
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for item in node.get('items') or []:
                if not isinstance(item, dict) or item.get('kind') not in (
                        'video', 'pptx', 'doc', 'geogebra', 'link'):
                    continue
                vis = item.get('visible') or {}
                if isinstance(vis, dict) and vis.get('student', True) is False:
                    continue
                path = _lesson_item_abs_path(res, item)
                if path and os.path.normcase(path) == os.path.normcase(abs_path):
                    return True
            if walk(node.get('children')):
                return True
        return False

    return walk(tree)


@resources_bp.route(
    '/study/lesson/<int:resource_id>/item/<item_id>/content/<path:filename>')
def lesson_item_content(resource_id, item_id, filename):
    """保留课件目录结构的课堂入口；相对导航仍逐文件校验权限。"""
    from flask import send_file
    from app.utils import has_dot_segment, has_win_path_alias

    res = db.get_or_404(Resource, resource_id)
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not _lesson_resource_accessible(res, is_teacher):
        abort(404)
    item = _find_lesson_item(res, item_id, is_teacher)
    if not item or not _lesson_item_abs_path(res, item):
        abort(404)
    if (filename.startswith('/') or '//' in filename or '\\' in filename
            or has_dot_segment(filename) or has_win_path_alias(filename)):
        abort(404)
    abs_path = _lesson_item_abs_path(res, {'src': filename})
    if not abs_path or not os.path.isfile(abs_path):
        abort(404)
    if not is_teacher:
        try:
            perms = _json.loads(res.file_permissions or '{}')
        except (TypeError, ValueError):
            perms = {}
        denied = isinstance(perms, dict) and any(
            str(key).lower() == filename.lower()
            and isinstance(value, dict) and value.get('show') is False
            for key, value in perms.items())
        if (denied and not res.allow_related_files
                and not _lesson_tree_allows_file(res, abs_path)):
            abort(403)
    resp = send_file(abs_path, conditional=True)
    resp.headers['Cache-Control'] = 'private, no-store'
    # 与课件静态目录一致：sandbox 的无凭据 fetch/module 可读，不授予凭据 CORS。
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


@resources_bp.route(
    '/study/lesson/<int:resource_id>/item/<item_id>/pptist-cache')
def lesson_item_pptist_cache(resource_id, item_id):
    """课堂条目对应的 PPTist 编辑缓存（<课件>.pptist.json）。

    与条目文件同权限；缓存不存在时 404，前端回退解析原始 PPTX。
    """
    from flask import send_file
    res = db.get_or_404(Resource, resource_id)
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not _lesson_resource_accessible(res, is_teacher):
        abort(404)
    item = _find_lesson_item(res, item_id, is_teacher)
    if not item:
        abort(404)
    abs_path = _lesson_item_abs_path(res, item)
    cache_path = (abs_path + '.pptist.json') if abs_path else None
    if not cache_path or not os.path.isfile(cache_path):
        abort(404)
    resp = send_file(cache_path, mimetype='application/json',
                     conditional=True)
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@resources_bp.route('/study/geogebra/<int:res_id>')
def geogebra_player(res_id):
    """GeoGebra（.ggb）课堂播放器。

    离线渲染：本地 GeoGebra Math Apps（static/geogebra/），不依赖公网 CDN。
    访问控制与课件文件一致：管理员全放行；教师限可见/课堂授权资源；
    学生按「任课教师范围 + 公开/内置」校验，并受文件级
    「展示」隐藏约束；匿名受课件公开开关约束。.ggb 可含 GeoGebra 脚本，
    静态文件的同源读取仍受 `_enforce_courseware_permissions` 与
    CSP（connect-src 'self'）约束。
    """
    from app.utils import has_dot_segment, has_win_path_alias

    res = db.session.get(Resource, res_id)
    if not res:
        abort(404)
    rel = request.args.get('file') or ''
    if (not rel.lower().endswith('.ggb') or '\x00' in rel
            or rel.startswith('/') or '//' in rel
            or has_dot_segment(rel) or has_win_path_alias(rel)):
        abort(404)
    dir_name = _resource_upload_dir(res)
    if (not dir_name or not _resource_dir_name(dir_name)
            or has_dot_segment(dir_name) or has_win_path_alias(dir_name)):
        abort(404)
    uploads_root = os.path.realpath(
        os.path.join(_BASE, 'static', 'uploads'))
    dir_root = os.path.realpath(os.path.join(uploads_root, dir_name))
    abs_path = os.path.realpath(os.path.join(dir_root, rel))
    if not (abs_path == dir_root or abs_path.startswith(dir_root + os.sep)) \
            or not os.path.isfile(abs_path):
        abort(404)

    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if session.get('is_admin'):
        pass
    elif is_teacher:
        mode = session.get('teacher_mode') or 'edit'
        allowed = teacher_can_view(
            res, session.get('teacher_id'), is_admin=False, mode=mode)
        if not allowed and res.show_in_classroom:
            allowed = teacher_can_use_resource(res, session.get('teacher_id'))
        if not allowed:
            abort(404)
    elif session.get('student_id'):
        student = db.session.get(Student, session.get('student_id'))
        if not student_can_access_resource(res, student):
            abort(404)
    else:
        from app.models import SystemConfig as _SC
        if not _SC.get_bool('courseware_public_enabled', True):
            return redirect(url_for('auth.login'))
        if not res.show_in_student:
            abort(404)

    if not is_teacher:
        # 权限键与 Windows 文件名保持同一大小写口径，主页仍固定展示。
        url_file = ''
        if res.url and res.url.startswith('/static/uploads/'):
            parts = res.url[len('/static/uploads/'):].split('/', 1)
            if len(parts) == 2:
                url_file = parts[1]
        if rel.lower() != url_file.lower():
            try:
                perms = _json.loads(res.file_permissions or '{}')
            except (TypeError, ValueError):
                perms = {}
            if (isinstance(perms, dict) and any(
                    str(key).lower() == rel.lower()
                    and isinstance(value, dict) and value.get('show') is False
                    for key, value in perms.items())
                    and not res.allow_related_files):
                abort(404)

    return render_template(
        'geogebra_player.html',
        res=res,
        file_name=rel.rsplit('/', 1)[-1],
        file_url=url_for('static', filename=f'uploads/{dir_name}/{rel}'),
        embed=request.args.get('embed') == '1')


_GGB_BRIDGE_MAX_BYTES = 10 * 1024 * 1024
_THREE_VERSIONS = ('0.186.1',)
_COURSEWARE_ACCESS_SECONDS = 3600


def _courseware_signer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt='itstudy-courseware-read-v1')


def _courseware_actor(allow_public=False):
    from app.models import AdminAccount
    from app.utils import password_fingerprint, read_admin_account

    if (allow_public and not session.get('student_id')
            and not session.get('is_teacher') and not session.get('is_admin')):
        # 公开资源允许匿名只读访问：actor 只标记身份类型，实际资源可见性
        # 由 _courseware_resource_allowed 按 show_in_student 与公开开关校验。
        return {'kind': 'public'}
    if session.get('is_admin'):
        kind, actor_id = 'admin', session.get('admin_account_id')
        account = db.session.get(AdminAccount, actor_id) if actor_id else None
        if account:
            fingerprint = password_fingerprint(account.password_hash)
        else:
            try:
                _, file_hash = read_admin_account()
                fingerprint = password_fingerprint(file_hash)
            except Exception:
                fingerprint = ''
    elif session.get('is_teacher'):
        kind, actor_id = 'teacher', session.get('teacher_id')
        account = db.session.get(Teacher, actor_id) if actor_id else None
        fingerprint = password_fingerprint(account.password_hash if account else '')
    else:
        kind, actor_id = 'student', session.get('student_id')
        account = db.session.get(Student, actor_id) if actor_id else None
        fingerprint = password_fingerprint(account.password_hash if account else '')
    actor = {'kind': kind, 'id': actor_id,
             'fingerprint': (fingerprint if kind == 'admin' and not actor_id
                             else session.get('pwd_fp') or fingerprint)}
    if kind == 'teacher':
        actor.update(mode=session.get('teacher_mode') or 'edit',
                     readonly_fp=session.get('readonly_code_fp') or '')
    if kind == 'student':
        actor.update(class_id=account.class_id if account else None,
                     classroom_bound=bool(session.get('classroom_bound')))
    return actor


def _courseware_actor_valid(actor):
    from app.models import AdminAccount, ClassroomSession, ClassroomSetting
    from app.utils import password_fingerprint, read_admin_account
    from app.blueprints.auth import TEACHER_READONLY_CODE_KEY

    kind, actor_id = actor.get('kind'), actor.get('id')
    if kind == 'public':
        # 匿名公开凭证没有账号可复核；由资源级校验确认 show_in_student
        # 与 courseware_public_enabled，并受签名 grant 的资源/目录/来源绑定。
        return True
    if kind == 'admin' and actor_id is None:
        try:
            _, file_hash = read_admin_account()
        except Exception:
            return False
        return bool(actor.get('fingerprint')) and secrets.compare_digest(
            actor['fingerprint'], password_fingerprint(file_hash))
    model = {'admin': AdminAccount, 'teacher': Teacher, 'student': Student}.get(kind)
    account = db.session.get(model, actor_id) if model and actor_id else None
    if not account or not secrets.compare_digest(
            actor.get('fingerprint') or '', password_fingerprint(account.password_hash)):
        return False
    if kind in ('admin', 'teacher') and not account.is_active:
        return False
    if kind == 'teacher' and actor.get('mode') == 'readonly':
        code = db.session.get(SystemConfig, TEACHER_READONLY_CODE_KEY)
        if not code or not actor.get('readonly_fp') or not secrets.compare_digest(
                actor['readonly_fp'], password_fingerprint(code.value)):
            return False
    if kind == 'student':
        if (not account.is_activated or not account.has_changed_password
                or account.class_id != actor.get('class_id')
                or not SystemConfig.get_bool('student_access_enabled', True)):
            return False
        active = {row.class_id for row in ClassroomSession.query.filter_by(is_active=True).all()}
        if not active:
            setting = ClassroomSetting.query.first()
            if setting and setting.active_class_id:
                active.add(setting.active_class_id)
        if (actor.get('classroom_bound') and account.class_id not in active
                or active and account.class_id not in active):
            return False
    return True


def _courseware_resource_allowed(res, actor):
    # 一个课件页会请求数百个模块/图片；短期缓存授权结果，键含资源写版本，
    # 权限变更立即换代，账号状态最长滞后 10 秒（与既有会话校验同口径）。
    version = cache.get('study:resources:scope:version') or 0
    key_actor = actor
    if actor.get('kind') == 'public':
        # 公开开关变化立即换代，不能沿用关闭前的授权缓存。
        key_actor = dict(actor, public_enabled=SystemConfig.get_bool(
            'courseware_public_enabled', True))
    key = 'courseware:grant:' + hashlib.sha256(_json.dumps(
        {'actor': key_actor, 'resource_id': res.id, 'version': version},
        sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return bool(hit)
    allowed = _courseware_resource_allowed_uncached(res, actor)
    cache.set(key, allowed, timeout=10)
    return allowed


def _courseware_resource_allowed_uncached(res, actor):
    if not _courseware_actor_valid(actor):
        return False
    if actor['kind'] == 'admin':
        return True
    if actor['kind'] == 'public':
        return bool(res.show_in_student and SystemConfig.get_bool(
            'courseware_public_enabled', True))
    if actor['kind'] == 'teacher':
        return bool(teacher_can_view(res, actor['id'], mode=actor.get('mode') or 'edit')
                    or res.show_in_classroom and teacher_can_use_resource(res, actor['id']))
    from app.services.resource_access import student_classroom_scope
    student = db.session.get(Student, actor['id'])
    scoped, public = student_classroom_scope(student.class_id)
    return any(item.id == res.id for item in scoped + public)


def _courseware_checked_file(res, path, actor, *, allow_tree=False):
    from app.utils import has_dot_segment, has_win_path_alias

    if (not path or path.startswith('/') or '//' in path or '\\' in path
            or re.search(r'[\x00-\x1f\x7f]', path)
            or has_dot_segment(path) or has_win_path_alias(path)
            or any(part.startswith('.') for part in path.split('/'))
            or path.lower().endswith('.bak')):
        abort(404)
    dir_name = _resource_upload_dir(res)
    if (not dir_name or not _resource_dir_name(dir_name)
            or has_dot_segment(dir_name) or has_win_path_alias(dir_name)):
        abort(404)
    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    dir_root = os.path.realpath(os.path.join(uploads_root, dir_name))
    abs_path = os.path.realpath(os.path.join(dir_root, path))
    if (not os.path.normcase(dir_root).startswith(os.path.normcase(uploads_root) + os.sep)
            or not os.path.normcase(abs_path).startswith(os.path.normcase(dir_root) + os.sep)
            or not os.path.isfile(abs_path) or not _courseware_resource_allowed(res, actor)):
        abort(404)
    if actor['kind'] in ('student', 'public'):
        main_file = (res.url or '').partition(f'/static/uploads/{dir_name}/')[2]
        if path.lower() != main_file.lower():
            try:
                perms = _json.loads(res.file_permissions or '{}')
            except (TypeError, ValueError):
                perms = {}
            denied = isinstance(perms, dict) and any(
                str(key).lower() == path.lower()
                and isinstance(value, dict) and value.get('show') is False
                for key, value in perms.items())
            # “允许打开页面相关链接”只放开读取，不改变 /study 的文件列表；
            # 自包含课件的子页面与 CSS/JS/图片等依赖仍需统一放行。
            if (denied and not res.allow_related_files
                    and not (allow_tree and _lesson_tree_allows_file(
                        res, abs_path))):
                abort(404)
    return dir_name, dir_root, abs_path


def _issue_courseware_access(res, path, *, classroom=False, allow_public=False):
    actor = _courseware_actor(allow_public=allow_public)
    dir_name, _, _ = _courseware_checked_file(res, path, actor, allow_tree=classroom)
    bridge_token = secrets.token_urlsafe(24)
    grant = _courseware_signer().dumps({
        'resource_id': res.id, 'dir_name': dir_name, 'actor': actor,
        'origin': request.host_url.rstrip('/'), 'bridge_token': bridge_token,
        'classroom': classroom,
    })
    base_url = url_for('resources.courseware_view', access_token=grant,
                       resource_id=res.id, relpath='_')[:-1]
    return {'base_url': base_url, 'bridge_token': bridge_token}


@resources_bp.route('/study/courseware-access/<int:resource_id>')
def courseware_access(resource_id):
    """课堂/学习页课件读取凭证。

    登录用户按既有账号/资源权限签发；匿名访客仅对 show_in_student 的
    公开资源签发（仍受 courseware_public_enabled 与文件级隐藏约束）。
    """
    res = db.get_or_404(Resource, resource_id)
    path = request.args.get('file') or ''
    if not path.lower().endswith(('.html', '.htm')):
        abort(404)
    response = jsonify(success=True, **_issue_courseware_access(
        res, path, classroom=True, allow_public=True))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@resources_bp.route('/study/courseware-view/<access_token>/<int:resource_id>/<path:relpath>')
def courseware_view(access_token, resource_id, relpath):
    if len(access_token) > 2048:
        abort(404)
    try:
        grant = _courseware_signer().loads(access_token, max_age=_COURSEWARE_ACCESS_SECONDS)
    except BadSignature:
        abort(404)
    res = db.get_or_404(Resource, resource_id)
    if (not isinstance(grant, dict) or grant.get('resource_id') != resource_id
            or grant.get('dir_name') != _resource_upload_dir(res)
            or grant.get('origin') != request.host_url.rstrip('/')
            or not isinstance(grant.get('actor'), dict)):
        abort(404)
    root = url_for('resources.courseware_view', access_token=access_token,
                   resource_id=resource_id, relpath='_')[:-1]
    return _serve_courseware(
        res, relpath, grant['actor'], root,
        grant.get('bridge_token') or '', grant['origin'],
        allow_tree=bool(grant.get('classroom')))


@resources_bp.route('/study/courseware/<int:resource_id>/<path:relpath>')
@authenticated_required
def courseware_frame(resource_id, relpath):
    res = db.get_or_404(Resource, resource_id)
    token = request.args.get('token') or ''
    if not re.fullmatch(r'[0-9A-Za-z_-]{1,128}', token):
        token = ''
    origin = request.args.get('origin') or ''
    if origin != request.host_url.rstrip('/'):
        origin = ''
    root = url_for('resources.courseware_frame', resource_id=resource_id, relpath='_')[:-1]
    return _serve_courseware(res, relpath, _courseware_actor(), root,
                             token, origin, allow_tree=True)


def _serve_courseware(res, path, actor, root, bridge_token, origin, *, allow_tree):
    from flask import send_file
    from html import escape
    from urllib.parse import quote
    from app.utils import adapt_courseware_css, adapt_courseware_script, versioned_static

    dir_name, dir_root, abs_path = _courseware_checked_file(res, path, actor, allow_tree=allow_tree)
    ext = path.rsplit('.', 1)[-1].lower()
    if ext not in ('html', 'htm', 'js', 'mjs', 'css') or os.path.getsize(abs_path) > _GGB_BRIDGE_MAX_BYTES:
        response = send_file(abs_path, conditional=True)
    else:
        with open(abs_path, 'rb') as fh:
            data = fh.read()
        charset = 'utf-8-sig'
        declared = re.search(br'charset\s*=\s*["\']?\s*([\w.-]+)', data[:2048], re.I)
        if declared:
            import codecs
            try:
                charset = codecs.lookup(declared.group(1).decode('ascii')).name
            except LookupError:
                pass
        try:
            text = data.decode(charset)
        except (UnicodeDecodeError, LookupError):
            response = send_file(abs_path, conditional=True)
        else:
            if ext in ('html', 'htm'):
                text, _ = adapt_courseware_html(text, dir_root, path, dir_name, target_root=root)
                text = re.sub(r'<base\b[^>]*>', '', text, flags=re.I)
                base_url = root + quote(path, safe='/')
                script_tag = ('<script src="{}" data-host-origin="{}" data-token="{}" '
                              'data-resource-root="{}" data-content-root="{}"></script>').format(
                    escape(versioned_static('js/ggb-courseware-bootstrap.js')), escape(origin),
                    escape(bridge_token), escape(f'/static/uploads/{dir_name}/'), escape(root))
                injection = '<base href="{}">{}'.format(escape(base_url), script_tag)
                matched = re.search(r'<head\b[^>]*>', text, re.I)
                if not matched:
                    matched = re.search(r'<html\b[^>]*>', text, re.I)
                at = matched.end() if matched else 0
                text = text[:at] + injection + text[at:]
                mime = 'text/html'
            elif ext in ('js', 'mjs'):
                text = adapt_courseware_script(text, dir_root, path, dir_name, root)
                mime = 'text/javascript'
            else:
                text = adapt_courseware_css(text, dir_root, path, dir_name, root)
                mime = 'text/css'
            response = Response(text, mimetype=mime)
    response.headers['Cache-Control'] = 'private, no-store'
    # 无凭据 CORS：opaque sandbox 的 fetch/Worker 请求 Origin: null；
    # 通配符不携带凭据，浏览器会拒绝任何带 Cookie 的跨源读取。
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@resources_bp.route('/study/three/<version>/<path:filename>')
def three_vendor_module(version, filename):
    """上传课件依赖的 three.js 本地模块（CDN 引用改写目标）。

    无登录限制：课件在 opaque 沙箱内以 ES 模块导入加载，无法携带凭据；
    版本白名单 + 目录包含校验，内容与版本绑定后 immutable 缓存。
    """
    from flask import send_file
    from app.utils import has_dot_segment, has_win_path_alias
    if version not in _THREE_VERSIONS:
        abort(404)
    if (not filename or filename.startswith('/') or '//' in filename
            or '\\' in filename or '\x00' in filename
            or has_dot_segment(filename) or has_win_path_alias(filename)):
        abort(404)
    three_root = os.path.realpath(os.path.join(_BASE, 'static', 'three'))
    abs_path = os.path.realpath(os.path.join(three_root, filename))
    if (os.path.normcase(abs_path) == os.path.normcase(three_root)
            or not os.path.normcase(abs_path).startswith(
                os.path.normcase(three_root) + os.sep)
            or not os.path.isfile(abs_path)):
        abort(404)
    resp = send_file(abs_path, conditional=True,
                     mimetype='text/javascript' if filename.lower().endswith('.js') else None)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


@resources_bp.route('/study/lesson/<int:resource_id>/online')
@teacher_login_required
def lesson_online(resource_id):
    """课堂页在线人数与名单（复用考勤快照口径：30 分钟内心跳视为在线）"""
    from app.blueprints.teaching import _attendance_snapshot
    snap = _attendance_snapshot()
    return jsonify({'success': True,
                    'online_count': snap['online_count'],
                    'total': snap['total'],
                    'class_name': snap['class_name'],
                    'students': snap['students']})


@resources_bp.route('/study/lesson/<int:resource_id>/mindmap/list')
@authenticated_required
def lesson_mindmap_list(resource_id):
    """课件目录内已保存的思维导图列表

    可见性与课堂页（study_lesson）同口径：学生按「当前授课教师范围 +
    公开/内置」校验；教师/管理员全量可读。此前仅鉴权登录，学生可按 ID
    枚举"对学生隐藏"资源（show_in_student=false）的思维导图文件清单。
    """
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not is_teacher and _student_resource_out_of_scope(res):
        return jsonify({'success': False, 'msg': '资源不可访问'}), 403
    dir_name = _resource_upload_dir(res)
    out = []
    if dir_name:
        dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
        if os.path.isdir(dir_path):
            for fn in os.listdir(dir_path):
                if fn.startswith(MINDMAP_PREFIX) and fn.endswith('.json'):
                    out.append(fn)
    return jsonify({'success': True, 'files': sorted(out)})


@resources_bp.route('/study/lesson/<int:resource_id>/mindmap')
@authenticated_required
def lesson_mindmap_get(resource_id):
    """读取课件目录内已保存的思维导图内容（可见性与 mindmap/list 同口径）"""
    name = (request.args.get('name') or '').strip()
    if not _MINDMAP_NAME_RE.match(name):
        return jsonify({'success': False, 'msg': '文件名不合法'}), 400
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    is_teacher = bool(session.get('is_admin') or session.get('is_teacher'))
    if not is_teacher and _student_resource_out_of_scope(res):
        return jsonify({'success': False, 'msg': '资源不可访问'}), 403
    dir_name = _resource_upload_dir(res) if res else None
    if not dir_name:
        return jsonify({'success': False, 'msg': '该资源不支持思维导图存储'}), 400
    path = os.path.join(_BASE, 'static', 'uploads', dir_name, name)
    if not os.path.isfile(path):
        return jsonify({'success': False, 'msg': '思维导图不存在'}), 404
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            data = _json.load(f)
    except Exception:
        current_app.logger.warning('思维导图读取失败: %s/%s', dir_name, name,
                                   exc_info=True)
        return jsonify({'success': False, 'msg': '思维导图文件损坏'}), 500
    return jsonify({'success': True, 'name': name, 'data': data})


@resources_bp.route('/study/lesson/<int:resource_id>/mindmap/save', methods=['POST'])
@teacher_login_required
def lesson_mindmap_save(resource_id):
    """保存思维导图到课件目录（教师/管理员），供下次打开。

    信任模型：教师为受信角色，但写入边界限定为"课堂可见"资源（与课堂
    页入口的可见性一致），避免越权向不可见资源的课件目录写文件。"""
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
    if not res.show_in_classroom:
        return jsonify({'success': False, 'msg': '该资源不在课堂端，禁止写入'}), 403
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({'success': False, 'msg': '外链资源不支持思维导图存储'}), 400
    payload = json_body_or_empty()
    name = str(payload.get('name') or '').strip()[:60]
    if not name:
        return jsonify({'success': False, 'msg': '请填写思维导图名称'}), 400
    filename = f'{MINDMAP_PREFIX}{name}.json'
    if not _MINDMAP_NAME_RE.match(filename):
        return jsonify({'success': False, 'msg': '名称仅支持中文/字母/数字/-_'}), 400
    data = payload.get('data')
    if not isinstance(data, dict):
        return jsonify({'success': False, 'msg': '导图数据格式错误'}), 400
    raw = _json.dumps(data, ensure_ascii=False)
    if len(raw.encode('utf-8')) > _MINDMAP_MAX_BYTES:
        return jsonify({'success': False, 'msg': '导图数据过大（上限 2MB）'}), 400
    dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
    try:
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, filename), 'w', encoding='utf-8') as f:
            f.write(raw)
    except OSError:
        current_app.logger.error('思维导图保存失败: %s/%s', dir_name, filename,
                                 exc_info=True)
        return jsonify({'success': False, 'msg': '保存失败（磁盘错误）'}), 500
    cache.delete(f'study:files:{dir_name}')
    db.session.add(Log(user_id=0,
                       user_type='admin' if session.get('is_admin') else 'teacher',
                       action='保存课堂思维导图',
                       detail=f'资源: {res.title} / 文件: {filename}',
                       time=datetime.now()))
    db.session.commit()
    return jsonify({'success': True, 'file': filename, 'msg': '已保存到课件目录'})


def _tool_doc_prefix(tool):
    return _TOOL_DOC_PREFIXES.get(tool)


def _lesson_tool_doc_accessible(res):
    """课堂图板文档可见性与课堂页同口径：学生按「当前授课教师范围 +
    公开/内置」校验（授课教师范围内不要求 show_in_student）。"""
    if session.get('is_admin') or session.get('is_teacher'):
        return True
    return not _student_resource_out_of_scope(res)


@resources_bp.route('/study/lesson/<int:resource_id>/tool-docs/list')
@authenticated_required
def lesson_tool_doc_list(resource_id):
    """列出课件目录内某个课堂图板应用保存的文档。"""
    tool = (request.args.get('tool') or '').strip()
    prefix = _tool_doc_prefix(tool)
    if not prefix:
        return jsonify({'success': False, 'msg': '不支持的图板类型'}), 400
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not _lesson_tool_doc_accessible(res):
        return jsonify({'success': False, 'msg': '资源不可访问'}), 403
    dir_name = _resource_upload_dir(res)
    out = []
    if dir_name:
        dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
        if os.path.isdir(dir_path):
            for fn in os.listdir(dir_path):
                if fn.startswith(prefix) and fn.endswith('.json'):
                    out.append(fn)
    return jsonify({'success': True, 'files': sorted(out)})


@resources_bp.route('/study/lesson/<int:resource_id>/tool-docs/get')
@authenticated_required
def lesson_tool_doc_get(resource_id):
    """读取课件目录内的课堂图板文档内容。"""
    tool = (request.args.get('tool') or '').strip()
    prefix = _tool_doc_prefix(tool)
    if not prefix:
        return jsonify({'success': False, 'msg': '不支持的图板类型'}), 400
    name = (request.args.get('name') or '').strip()
    if not _TOOL_DOC_NAME_RE.match(name) or not name.startswith(prefix):
        return jsonify({'success': False, 'msg': '文件名不合法'}), 400
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not _lesson_tool_doc_accessible(res):
        return jsonify({'success': False, 'msg': '资源不可访问'}), 403
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({'success': False, 'msg': '该资源不支持图板存储'}), 400
    path = os.path.join(_BASE, 'static', 'uploads', dir_name, name)
    if not os.path.isfile(path):
        return jsonify({'success': False, 'msg': '文档不存在'}), 404
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            data = _json.load(f)
    except Exception:
        current_app.logger.warning('课堂图板文档读取失败: %s/%s', dir_name, name,
                                   exc_info=True)
        return jsonify({'success': False, 'msg': '文档文件损坏'}), 500
    return jsonify({'success': True, 'name': name, 'data': data})


@resources_bp.route('/study/lesson/<int:resource_id>/tool-docs/save', methods=['POST'])
@teacher_api_required
def lesson_tool_doc_save(resource_id):
    """教师把流程拓扑图 / 思维导图保存到课件目录，供下次课堂打开。"""
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
    if not res.show_in_classroom:
        return jsonify({'success': False, 'msg': '该资源不在课堂端，禁止写入'}), 403
    payload = json_body_or_empty()
    tool = str(payload.get('tool') or '').strip()
    prefix = _tool_doc_prefix(tool)
    if not prefix:
        return jsonify({'success': False, 'msg': '不支持的图板类型'}), 400
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({'success': False, 'msg': '外链资源不支持图板存储'}), 400
    name = str(payload.get('name') or '').strip()[:60]
    if not name:
        return jsonify({'success': False, 'msg': '请填写名称'}), 400
    filename = f'{prefix}{name}.json'
    if not _TOOL_DOC_NAME_RE.match(filename):
        return jsonify({'success': False, 'msg': '名称仅支持中文/字母/数字/-_'}), 400
    data = payload.get('data')
    if not isinstance(data, dict):
        return jsonify({'success': False, 'msg': '图板数据格式错误'}), 400
    if tool == 'flow':
        nodes = data.get('nodes')
        if not isinstance(nodes, list) or not nodes:
            return jsonify({'success': False, 'msg': '画布上还没有图形，无法保存'}), 400
    elif not isinstance(data.get('root'), dict):
        return jsonify({'success': False, 'msg': '思维导图数据格式错误'}), 400
    raw = _json.dumps(data, ensure_ascii=False)
    if len(raw.encode('utf-8')) > _MINDMAP_MAX_BYTES:
        return jsonify({'success': False, 'msg': '图板数据过大（上限 2MB）'}), 400
    dir_path = os.path.join(_BASE, 'static', 'uploads', dir_name)
    try:
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, filename), 'w', encoding='utf-8') as f:
            f.write(raw)
    except OSError:
        current_app.logger.error('课堂图板保存失败: %s/%s', dir_name, filename,
                                 exc_info=True)
        return jsonify({'success': False, 'msg': '保存失败（磁盘错误）'}), 500
    cache.delete(f'study:files:{dir_name}')
    label = '流程拓扑图' if tool == 'flow' else '思维导图'
    db.session.add(Log(user_id=0,
                       user_type='admin' if session.get('is_admin') else 'teacher',
                       action=f'保存课堂{label}',
                       detail=f'资源: {res.title} / 文件: {filename}',
                       time=datetime.now()))
    db.session.commit()
    return jsonify({'success': True, 'file': filename, 'msg': '已保存到课件目录'})


@resources_bp.route('/study/lesson/<int:resource_id>/pptist/save', methods=['POST'])
@teacher_login_required
def lesson_pptist_save(resource_id):
    """保存 PPTX 课件的 PPTist 编辑缓存（<课件路径>.pptist.json 写入课件目录）。

    课堂页放映时优先读该缓存，无缓存则回退浏览器端解析原始 PPTX。
    信任模型与思维导图一致：教师受信，但仅限课堂可见资源。"""
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
    if not res.show_in_classroom:
        return jsonify({'success': False, 'msg': '该资源不在课堂端，禁止写入'}), 403
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({'success': False, 'msg': '外链资源不支持课件编辑'}), 400
    payload = json_body_or_empty()
    src = str(payload.get('src') or '').strip().replace('\\', '/')
    if (not src or src.startswith('/') or '..' in src.split('/')
            or not src.lower().endswith(('.pptx', '.ppt'))):
        return jsonify({'success': False, 'msg': '课件路径不合法（仅支持 PPTX）'}), 400
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('slides'), list):
        return jsonify({'success': False, 'msg': '课件数据格式错误'}), 400
    # 存储型 XSS 净化（与小组/个人网盘同型保存路径对齐）：PPTist 正文
    # 按 HTML 渲染，slides JSON 中的恶意片段会在全班浏览器同源执行
    from app.blueprints.student_groups import _sanitize_pptist_json
    try:
        data = _sanitize_pptist_json(data)
    except ValueError:
        return jsonify({'success': False, 'msg': '课件包含危险 HTML 内容'}), 400
    raw = _json.dumps(data, ensure_ascii=False)
    if len(raw.encode('utf-8')) > 20 * 1024 * 1024:
        return jsonify({'success': False, 'msg': '课件数据过大（上限 20MB）'}), 400
    dir_real = os.path.realpath(os.path.join(_BASE, 'static', 'uploads', dir_name))
    target = os.path.realpath(os.path.join(dir_real, src + '.pptist.json'))
    if not target.startswith(dir_real + os.sep):
        return jsonify({'success': False, 'msg': '课件路径不合法'}), 400
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(raw)
    except OSError:
        current_app.logger.error('课件 PPTist 缓存保存失败: %s/%s', dir_name, src,
                                 exc_info=True)
        return jsonify({'success': False, 'msg': '保存失败（磁盘错误）'}), 500
    cache.delete(f'study:files:{dir_name}')
    return jsonify({'success': True, 'msg': '课件已保存'})


@resources_bp.route('/admin/resources/<int:resource_id>/lesson_files')
@teacher_edit_required
def admin_resource_lesson_files(resource_id):
    """课堂编排器的资源根目录浏览接口（按目录懒加载）。

    返回 root/breadcrumb/entries；entries 同时包含 can_show=false 的文件，
    让管理员可以把「仅教师可见」的文档加入课堂编排，学生端可见性由条目的
    visible.student 控制。资源为外链或目录不存在时返回 supported=false，
    前端显示明确说明而不是空列表。
    """
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权查看该资源目录'}), 403
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({
            'success': True, 'supported': False,
            'msg': '该资源是外链资源，没有本地课件目录；请使用「网页/外链」条目。'
        })

    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    root_path = os.path.realpath(os.path.join(uploads_root, dir_name))
    if root_path == uploads_root or not root_path.startswith(uploads_root + os.sep) \
            or not os.path.isdir(root_path):
        return jsonify({
            'success': True, 'supported': False,
            'msg': '资源课件目录不存在或不可访问。'
        })

    raw_path = (request.args.get('path') or '').strip()
    if '\\' in raw_path:
        raw_path = raw_path.replace('\\', '/')
    if raw_path.startswith('/') or '\x00' in raw_path:
        return jsonify({'success': False, 'msg': '目录路径不合法'}), 400
    rel_path = raw_path.strip('/')
    if '..' in rel_path.split('/'):
        return jsonify({'success': False, 'msg': '目录路径不合法'}), 400
    target = os.path.realpath(os.path.join(root_path, rel_path))
    if target != root_path and not target.startswith(root_path + os.sep):
        return jsonify({'success': False, 'msg': '目录路径不合法'}), 400
    if not os.path.isdir(target):
        return jsonify({'success': False, 'msg': '目录不存在'}), 404

    try:
        perms = _json.loads(res.file_permissions) if res.file_permissions else {}
    except Exception:
        perms = {}
    if not isinstance(perms, dict):
        perms = {}
    else:
        perms = {str(k).replace('\\', '/'): v for k, v in perms.items()
                 if isinstance(v, dict)}
    try:
        homework_files = set(_json.loads(res.homework_files) if res.homework_files else [])
    except Exception:
        homework_files = set()
    homework_files = {str(x).replace('\\', '/') for x in homework_files}
    # URL 指向的文件：用于标记主页；目录 URL 没有主页文件
    url_path = res.url[len('/static/uploads/'):]
    url_parts = url_path.split('/')
    url_file = '/'.join(url_parts[1:]) if len(url_parts) > 1 else ''
    url_file = url_file.replace('\\', '/')

    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name.startswith('.') or entry.is_symlink():
                    continue
                rel = f'{rel_path}/{entry.name}' if rel_path else entry.name
                rel = rel.replace('\\', '/')
                if entry.is_dir(follow_symlinks=False):
                    entries.append({
                        'name': entry.name, 'path': rel, 'is_dir': True,
                        'kind': 'dir', 'size': 0, 'ext': '',
                    })
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                # 课堂页衍生文件（思维导图/PPTist 缓存）不应出现在编排器
                if rel.endswith('.pptist.json') or (
                        (rel.startswith(MINDMAP_PREFIX) or rel.startswith(FLOW_PREFIX)) and rel.endswith('.json')):
                    continue
                ext = entry.name.rsplit('.', 1)[-1].lower() if '.' in entry.name else ''
                kind = _lesson_file_kind(ext)
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                perm = perms.get(rel, {})
                entries.append({
                    'name': entry.name, 'path': rel, 'is_dir': False,
                    'ext': ext, 'kind': kind, 'size': size,
                    'can_show': perm.get('show', True) is not False,
                    'is_homework': rel in homework_files,
                    'is_homepage': rel == url_file,
                    'previewable': kind in ('video', 'pptx', 'link') or (
                        kind == 'doc' and _lesson_doc_previewable(ext)),
                })
    except OSError:
        current_app.logger.error('课堂编排目录读取失败: %s', target, exc_info=True)
        return jsonify({'success': False, 'msg': '目录读取失败'}), 500

    entries.sort(key=lambda e: (not e['is_dir'], e['name'].casefold()))
    breadcrumb = [{'name': '根目录', 'path': ''}]
    if rel_path:
        acc = []
        for seg in rel_path.split('/'):
            acc.append(seg)
            breadcrumb.append({'name': seg, 'path': '/'.join(acc)})
    return jsonify({
        'success': True, 'supported': True,
        'root': {'dir': dir_name, 'label': res.title,
                 'url': f'/static/uploads/{dir_name}/'},
        'path': rel_path, 'breadcrumb': breadcrumb, 'entries': entries,
    })


@resources_bp.route('/admin/resources/<int:resource_id>/lesson_tree', methods=['GET', 'POST'])
@teacher_edit_required
def admin_resource_lesson_tree(resource_id):
    """课堂编排树读取/保存（管理端编排面板）。POST 传 reset=true 恢复默认编排。"""
    res = db.session.get(Resource, resource_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
    if request.method == 'GET':
        try:
            tree = _json.loads(res.lesson_tree) if res.lesson_tree else []
        except Exception:
            tree = []
        return jsonify({'success': True, 'tree': tree})
    payload = json_body_or_empty()
    if payload.get('reset'):
        res.lesson_tree = None
        db.session.commit()
        return jsonify({'success': True, 'msg': '已恢复默认课堂编排'})
    tree, err = _sanitize_lesson_tree(payload.get('tree'),
                                      _resource_upload_dir(res) or '')
    if err:
        return jsonify({'success': False, 'msg': err}), 400
    res.lesson_tree = _json.dumps(tree, ensure_ascii=False)
    db.session.add(Log(user_id=0, user_type='admin', action='保存课堂编排',
                       detail=f'资源: {res.title}', time=datetime.now()))
    db.session.commit()
    return jsonify({'success': True, 'msg': '课堂编排已保存'})


@resources_bp.route('/study/link')
@authenticated_required
def study_link():
    """外链资源封装页 — 在 iframe 中加载外部页面并保留 AI 助手"""
    from urllib.parse import urlparse
    from re import fullmatch
    url = request.args.get('url', '').strip()
    title = request.args.get('title', '').strip() or '外部资源'
    resource_id = request.args.get('resource_id', '')
    quiz_mode = request.args.get('quiz_mode', 'inject')
    if not url:
        return '<h3>缺少 URL 参数</h3>', 400
    # 反斜杠会被浏览器按 '/' 归一：'/\evil.example.com' → '//evil.example.com'
    # 变成协议相对外部地址，绕过下方"必须以单个 / 开头"的相对路径判定，
    # 成为开放框架/钓鱼跳转（iframe src 与错误弹窗 <a href> 均取其值）。
    if '\\' in url:
        return '<h3>无效的 URL</h3>', 400
    parsed = urlparse(url)
    if parsed.scheme:
        if parsed.scheme not in ('http', 'https'):
            return '<h3>不支持的协议</h3>', 400
    elif url.startswith('//') or not url.startswith('/'):
        # 协议相对地址(//host)会被浏览器解析为外部绝对地址，等同开放框架/跳转，拒绝
        return '<h3>无效的 URL</h3>', 400
    requested_id = parse_int(resource_id)
    scoped_resource = db.session.get(Resource, requested_id) if requested_id else None
    if scoped_resource and not (session.get('is_admin')
                                or session.get('is_teacher')):
        student_id = session.get('student_id')
        student = (db.session.get(Student, student_id)
                   if student_id else None)
        if not student_can_access_resource(scoped_resource, student):
            return '<h3>该资源当前不在上课教师范围内</h3>', 403
    # 站内 GeoGebra 播放器需要 localStorage / 同源 postMessage；仅该受信
    # 播放器帧放行 allow-same-origin，其余课件仍保持 opaque origin 隔离。
    trusted_same_origin = bool(
        fullmatch(r'/study/geogebra/[1-9][0-9]*', parsed.path)
        and (not parsed.scheme or (
            parsed.scheme == request.scheme and parsed.netloc == request.host))
    )
    bridge_root = ''
    bridge_access = None
    upload_dir = _resource_upload_dir(scoped_resource) if scoped_resource else ''
    own_origin = not parsed.scheme or (
        parsed.scheme == request.scheme and parsed.netloc == request.host)
    external_site = bool(parsed.scheme in ('http', 'https') and not own_origin)
    if upload_dir and own_origin and parsed.path.lower().endswith(('.html', '.htm')):
        from urllib.parse import unquote
        prefix = '/static/uploads/' + upload_dir + '/'
        if unquote(parsed.path).startswith(prefix):
            bridge_root = prefix
            bridge_access = _issue_courseware_access(
                scoped_resource, unquote(parsed.path)[len(prefix):])
    return render_template('study_link.html', url=url, title=title,
                           resource_id=scoped_resource.id if scoped_resource else None,
                           quiz_mode=quiz_mode,
                           trusted_same_origin=trusted_same_origin,
                           external_site=external_site,
                           ggb_bridge_root=bridge_root,
                           courseware_access=bridge_access)


@resources_bp.route('/study/preview')
def study_preview():
    """学习资源文件在线预览 — 由 JitViewer 统一渲染（pdf/office/ofd 等）

    仅允许预览 /static/uploads/ 下的本地资源文件，做路径穿越防护。
    """
    # 课件公开开关：关闭后预览页仅登录用户可访问
    from app.models import SystemConfig as _SC
    from flask import session as _sess
    if not _SC.get_bool('courseware_public_enabled', True):
        if not (_sess.get('student_id') or _sess.get('is_admin')
                or _sess.get('is_teacher')):
            return redirect(url_for('auth.login'))
    file_url = request.args.get('file', '').strip()
    filename = request.args.get('name', '').strip()
    lesson_res_id = parse_int(request.args.get('lesson_res'))
    lesson_item_id = request.args.get('lesson_item', '').strip()
    if lesson_res_id and lesson_item_id:
        # 课堂章节条目预览：教师已在编排里把该条目设为学生可见，
        # 课堂内以条目可见性为准（不被文件级「展示」开关二次拦截）。
        # 文件路径由服务端从章节树解析，客户端不能借条目 id 指定任意文件。
        res = db.get_or_404(Resource, lesson_res_id)
        is_teacher = bool(session.get('is_admin')
                          or session.get('is_teacher'))
        if not _lesson_resource_accessible(res, is_teacher):
            abort(404)
        item = _find_lesson_item(res, lesson_item_id, is_teacher)
        real_path = _lesson_item_abs_path(res, item) if item else None
        if not real_path or not os.path.isfile(real_path):
            abort(404)
        file_url = url_for('resources.lesson_item_file',
                           resource_id=res.id, item_id=item['id'])
        if not filename:
            filename = str(item.get('title') or os.path.basename(real_path))
    else:
        if not file_url:
            return '<h3>缺少文件参数</h3>', 400

        # 安全校验：只允许 /static/uploads/ 路径，防止目录穿越
        if not file_url.startswith('/static/uploads/'):
            return '<h3>仅支持本地资源文件</h3>', 400
        real_path = os.path.realpath(os.path.join(_BASE, file_url.lstrip('/')))
        base_dir = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
        if not real_path.startswith(base_dir + os.sep):
            return '<h3>非法路径</h3>', 400
        if not os.path.exists(real_path):
            return '<h3>文件不存在</h3>', 404

        # 学生按「当前授课教师范围 + 公开/内置」校验所属资源：此前预览路由
        # 不做范围校验，学生可通过构造 file 参数预览范围外资源。文件级
        # 「展示」隐藏同样生效（主页文件固定展示，不受该开关约束）。
        student_id = session.get('student_id')
        if student_id:
            rel_url = file_url[len('/static/uploads/'):]
            dir_name = rel_url.split('/', 1)[0]
            owner_res = Resource.query.filter(
                Resource.url.startswith(f'/static/uploads/{dir_name}/')).first()
            if owner_res:
                student = db.session.get(Student, student_id)
                if not student_can_access_resource(owner_res, student):
                    return '<h3>该资源不在当前课堂范围内</h3>', 403
                rel = rel_url.split('/', 1)[1] if '/' in rel_url else ''
                main_file = owner_res.url[len(
                    f'/static/uploads/{dir_name}/'):]
                if rel and rel.lower() != main_file.lower():
                    try:
                        perms = _json.loads(owner_res.file_permissions or '{}')
                    except (TypeError, ValueError):
                        perms = {}
                    denied = isinstance(perms, dict) and any(
                        str(k).lower() == rel.lower()
                        and isinstance(v, dict) and v.get('show') is False
                        for k, v in perms.items())
                    if denied and not owner_res.allow_related_files:
                        return '<h3>该文件不向学生展示</h3>', 403

    if not filename:
        filename = os.path.basename(real_path)
    # 预览扩展名必须以真实文件为准：编排条目标题通常不含扩展名
    # （如“第一章 导学”），此前用标题判断 ext 会退化成“不支持预览”，
    # docx/pdf/md 等全部被误判。展示名补回真实扩展名。
    real_name = os.path.basename(real_path)
    real_ext = real_name.rsplit('.', 1)[-1].lower() if '.' in real_name else ''
    if real_ext and not filename.lower().endswith('.' + real_ext):
        filename = f'{filename}.{real_ext}'
    ext = real_ext

    # 判断媒体类型用于 JitViewer 不支持时的回退
    media_type_map = {
        'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
        'bmp': 'image', 'webp': 'image', 'svg': 'image',
        'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio', 'm4a': 'audio',
        'flac': 'audio', 'aac': 'audio', 'opus': 'audio', 'weba': 'audio',
        'aiff': 'audio', 'aif': 'audio',
        'mp4': 'video', 'webm': 'video', 'ogv': 'video', 'm4v': 'video',
        'mov': 'video',
        'txt': 'text', 'md': 'text', 'csv': 'text',
    }
    media_type = media_type_map.get(ext, '')

    return render_template('document_preview.html',
                           filename=filename,
                           file_url=file_url,
                           download_url=file_url,
                           media_type=media_type,
                           ext=ext,
                           back_url=url_for('resources.study'))



@resources_bp.route('/admin/subjects', methods=['POST'])
@admin_login_required
def add_subject():
    """添加学科"""
    name = request.form.get('name', '').strip()
    if name:
        if not Subject.query.filter_by(name=name).first():
            max_order = db.session.query(db.func.max(Subject.sort_order)).scalar() or 0
            db.session.add(Subject(name=name, sort_order=max_order + 1))
            db.session.commit()
            invalidate_lookup_cache('subjects')
            flash(f'学科 "{name}" 已添加', 'success')
        else:
            flash(f'学科 "{name}" 已存在', 'warning')
    return redirect(url_for('resources.admin_resources'))


@resources_bp.route('/admin/subjects/rename', methods=['POST'])
@admin_login_required
def rename_subject():
    """原地重命名学科：保留学科 id，教师任教学科/资源/授权关联不变。

    此前学科管理只有“新增/删除”；用删除再新建来改名会连带删除资源，
    或让任课教师与新学科 id 脱钩，学生随之看不到共享资源（404）。
    """
    sid = parse_int(request.form.get('sid'))
    name = (request.form.get('name') or '').strip()
    subject = db.session.get(Subject, sid) if sid else None
    if not subject:
        flash('学科不存在', 'danger')
        return redirect(url_for('resources.admin_resources'))
    if not name:
        flash('学科名称不能为空', 'warning')
        return redirect(url_for('resources.admin_resources'))
    if Subject.query.filter(Subject.name == name, Subject.id != subject.id).first():
        flash(f'学科 "{name}" 已存在，请使用其他名称', 'warning')
        return redirect(url_for('resources.admin_resources'))
    old_name = subject.name
    if name != old_name:
        subject.name = name
        db.session.commit()
        invalidate_lookup_cache('subjects')
        _invalidate_study_caches()
        flash(f'学科 "{old_name}" 已重命名为 "{name}"，资源和教师关联保持不变',
              'success')
    return redirect(url_for('resources.admin_resources'))


@resources_bp.route('/admin/subjects/delete-check')
@admin_login_required
def subject_delete_check():
    """删除学科前的资源检查：返回每个学科下的资源数量与名称，
    供前端在确认删除时醒目提示（同步删除其下所有资源）。"""
    ids_raw = request.args.get('ids', '')
    ids = [int(i) for i in ids_raw.split(',') if i.strip().isdigit()]
    if not ids:
        return jsonify({'success': False, 'message': '参数无效'}), 400
    subjects = Subject.query.filter(Subject.id.in_(ids)).all()
    result = []
    total_resources = 0
    for subj in subjects:
        resources = Resource.query.filter_by(subject_id=subj.id).order_by(
            Resource.id).all()
        total_resources += len(resources)
        result.append({
            'id': subj.id,
            'name': subj.name,
            'resource_count': len(resources),
            'resources': [r.title for r in resources[:8]],
            'more': max(0, len(resources) - 8),
        })
    return jsonify({'success': True, 'data': result,
                    'total_resources': total_resources})


@resources_bp.route('/admin/subjects/delete/<int:sid>', methods=['POST'])
@admin_login_required
def delete_subject(sid):
    """删除学科及其所有资源

    顺序说明：先删 DB 记录（含所有子表引用）并 commit 成功，再删磁盘目录。
    若先删磁盘、后删 DB，DB 失败时会留下"磁盘已删但记录仍指向不存在文件"的
    悬空状态；先删 DB 则磁盘删除失败仅残留孤儿目录（告警但回滚 DB 反而会
    使已删记录复活，故不回滚）。
    """
    subject = db.get_or_404(Subject, sid)
    # 该学科下挂有试卷时拒绝删除：Exam.subject_id FK 无级联，直接删除必 500
    # （此前缺陷：删除含试卷的学科 → IntegrityError → 永远无法删除）。
    # 与 delete_exam 的"先清理成绩"提示语义一致，由管理员先处理试卷。
    exam_count = Exam.query.filter_by(subject_id=sid).count()
    if exam_count > 0:
        flash(f'无法删除：该学科下还有 {exam_count} 份试卷，请先删除或转移试卷', 'danger')
        return redirect(url_for('resources.admin_resources'))
    resources = Resource.query.filter_by(subject_id=sid).all()
    # 教师学科关联/资源分享关联（FK 无级联，先清理后再删学科/资源）
    subj_resource_ids = [r.id for r in resources]
    if subj_resource_ids:
        db.session.execute(resource_share.delete().where(
            resource_share.c.resource_id.in_(subj_resource_ids)))
        db.session.execute(resource_audience.delete().where(
            resource_audience.c.resource_id.in_(subj_resource_ids)))
        # 问卷链（问卷/题目/答卷 FK 均无级联）：bulk 删除资源前必须清理
        _delete_surveys_for_resources(subj_resource_ids)
    # 其他内置资源的授权范围引用本学科（年级×学科授权，FK 无级联）
    db.session.execute(resource_audience.delete().where(
        resource_audience.c.subject_id == sid))
    db.session.execute(teacher_subject.delete().where(
        teacher_subject.c.subject_id == sid))
    # 收集待删磁盘目录，并清理资源子表引用（FK 无级联，不清理会 500）：
    # 资源内嵌测验成绩 + 教师上课教学记录
    dir_names = []
    for res in resources:
        ResourceQuizResult.query.filter_by(resource_id=res.id).delete(synchronize_session=False)
        quiz_analysis_cache.invalidate_analysis(res.id)
        TeachingSession.query.filter_by(resource_id=res.id).delete(synchronize_session=False)
        if res.url and res.url.startswith('/static/uploads/'):
            dir_names.append(res.url.replace('/static/uploads/', '', 1).split('/')[0])
    # 先删学习活动链（作品评价 → 作品 → 活动），再 bulk 删 Resource：
    # bulk delete 不触发 ORM 级联，直接删 Resource 会留下孤儿 LearningActivity/StudentWork
    activity_ids = [a.id for a in LearningActivity.query.filter(
        LearningActivity.resource_id.in_(
            db.session.query(Resource.id).filter(Resource.subject_id == sid)
        )
    ).all()]
    if activity_ids:
        work_ids = [w.id for w in StudentWork.query.filter(
            StudentWork.activity_id.in_(activity_ids)).all()]
        if work_ids:
            WorkEvaluation.query.filter(WorkEvaluation.work_id.in_(work_ids)).delete(synchronize_session=False)
        # 优秀作品阈值表（activity_id 唯一 FK 无级联，不清理会 500）
        ExcellenceThreshold.query.filter(
            ExcellenceThreshold.activity_id.in_(activity_ids)).delete(synchronize_session=False)
        StudentWork.query.filter(StudentWork.activity_id.in_(activity_ids)).delete(synchronize_session=False)
        LearningActivity.query.filter(LearningActivity.id.in_(activity_ids)).delete(synchronize_session=False)
    Resource.query.filter_by(subject_id=sid).delete()
    db.session.delete(subject)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'删除学科 {sid} 失败: {e}', exc_info=True)
        flash(f'删除学科 "{subject.name}" 失败，请稍后重试', 'danger')
        return redirect(url_for('resources.admin_resources'))
    invalidate_lookup_cache('subjects')
    cache.delete('study:resources:student')
    cache.delete('study:resources:classroom')
    # DB 提交成功后再删磁盘目录（顺序说明见函数 docstring）
    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    for dir_name in dir_names:
        try:
            dir_path = os.path.realpath(os.path.join(uploads_root, dir_name))
            if dir_path != uploads_root and dir_path.startswith(uploads_root + os.sep) \
                    and os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
                cache.delete(f'study:files:{dir_name}')
        except OSError as e:
            current_app.logger.warning(
                f'删除学科资源磁盘目录失败（忽略，仅残留孤儿目录）: {dir_path}, error={e}')
    flash(f'学科 "{subject.name}" 及其资源已删除', 'success')
    return redirect(url_for('resources.admin_resources'))


def _check_upload_file_size(file_storage, max_bytes):
    """检查上传文件大小（Content-Length 优先，避免读流）。返回 (ok, message)。"""
    length = getattr(file_storage, 'content_length', None)
    if length is not None:
        if length > max_bytes:
            return False, f'文件超过 {max_bytes // (1024 * 1024)}MB 限制'
        return True, ''
    # 无 Content-Length（chunked）：读一个字节触发流初始化后按剩余位置估算
    try:
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size > max_bytes:
            return False, f'文件超过 {max_bytes // (1024 * 1024)}MB 限制'
        return True, ''
    except Exception:
        return True, ''  # 无法估算时放行，落盘后仍有全局限制兜底


@resources_bp.route('/admin/resources/<int:res_id>/upload_files', methods=['POST'])
@teacher_edit_required
def upload_files_to_resource(res_id):
    """向已上传资源新增或替换文件/文件夹（编辑页使用）。

    replace=1 时覆盖同名文件；否则沿用“文件名 (1)”自动避让。
    只允许写入该资源自己的 static/uploads/<dir>/ 目录。
    """
    res = db.session.get(Resource, res_id)
    if not res:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(res, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
    dir_name = _resource_upload_dir(res)
    if not dir_name:
        return jsonify({'success': False, 'msg': '该资源不是本地文件资源'}), 400
    subfolder = request.form.get('subfolder', '').strip()
    replace = request.form.get('replace') == '1'
    files = []
    for field_name in ('files', 'folder', 'file', 'upload', 'resource_files'):
        files.extend(request.files.getlist(field_name))
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({'success': False, 'msg': '未选择文件'}), 400

    base_dir = os.path.join(_BASE, 'static', 'uploads', dir_name)
    if subfolder:
        subfolder_clean = secure_filename_with_unicode(subfolder)
        if not subfolder_clean:
            return jsonify({'success': False, 'msg': '子目录名不合法'}), 400
        target_dir = os.path.join(base_dir, subfolder_clean)
    else:
        target_dir = base_dir
    os.makedirs(target_dir, exist_ok=True)
    target_real = os.path.realpath(target_dir)
    saved, replaced, injected = [], [], []
    pending_new = []
    try:
        for file in files:
            raw_path = file.filename.replace('\\', '/').lstrip('/')
            if not raw_path or '..' in raw_path.split('/'):
                return jsonify({'success': False, 'msg': '非法文件名'}), 400
            ext = os.path.splitext(raw_path)[1].lower().lstrip('.')
            reject_msg = _resource_reject_message(raw_path)
            if reject_msg:
                return jsonify({'success': False, 'msg': reject_msg}), 400
            ok, err = _check_upload_file_size(file, 200 * 1024 * 1024)
            if not ok:
                return jsonify({'success': False, 'msg': err}), 413
            dest = os.path.realpath(os.path.join(target_real, raw_path))
            if dest == target_real or not dest.startswith(target_real + os.sep):
                return jsonify({'success': False, 'msg': '非法文件路径'}), 400
            rel_path = os.path.relpath(dest, target_real).replace('\\', '/')
            was_existing = os.path.exists(dest)
            if was_existing and not replace:
                base_name, suffix = os.path.splitext(raw_path)
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.realpath(os.path.join(
                        target_real, f'{base_name} ({counter}){suffix}'))
                    counter += 1
                rel_path = os.path.relpath(dest, target_real).replace('\\', '/')
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            # 先写 .part 再原子替换，避免覆盖过程中留下半文件
            part = dest + '.part'
            try:
                file.save(part)
                os.replace(part, dest)
            finally:
                if os.path.exists(part):
                    try:
                        os.remove(part)
                    except OSError:
                        pass
            if was_existing and replace:
                replaced.append(rel_path)
                # gzip_static 可能仍下发旧的 .gz，覆盖后必须移除
                gz = dest + '.gz'
                if os.path.isfile(gz):
                    try:
                        os.remove(gz)
                    except OSError:
                        pass
            saved.append(rel_path)
            if ext in ('html', 'htm') and (res.quiz_mode or 'inject') == 'inject':
                source_rel = os.path.relpath(dest, base_dir).replace('\\', '/')
                pending_new.append(source_rel)
        _invalidate_study_caches(dir_name)
        if pending_new:
            pending = sorted(set(_quiz_pending_files(res)) | set(pending_new))
            res.quiz_pending_files = _json.dumps(pending, ensure_ascii=False)
            res.quiz_inject_state = 'pending'
        db.session.add(Log(
            user_id=0, user_type='admin', action='上传/替换学习资源文件',
            detail=f'资源: {res.title}, 保存 {len(saved)} 个, 替换 {len(replaced)} 个',
            time=datetime.now()))
        db.session.commit()
        msg = f'已保存 {len(saved)} 个文件'
        if pending_new:
            msg += '；请完成注入检测后应用采集脚本'
        return jsonify({'success': True, 'files': saved, 'replaced': replaced,
                        'injected': injected, 'needs_check': bool(pending_new),
                        'msg': msg})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('资源文件上传/替换失败: %s', exc, exc_info=True)
        return jsonify({'success': False, 'msg': '文件保存失败'}), 500


@resources_bp.route('/admin/resources/upload', methods=['POST'])
@teacher_edit_required
def upload_resource_files():
    """处理资源文件上传 — 仅上传文件，返回文件列表"""
    try:
        title = request.form.get('title')
        subfolder = request.form.get('subfolder', '').strip()

        if not title:
            return jsonify({'success': False, 'msg': '资源标题不能为空'})
        files = None
        for field_name in ['files', 'file', 'upload', 'resource_files']:
            if field_name in request.files:
                files = request.files.getlist(field_name)
                if files and files[0].filename:
                    break
        if not files or not files[0].filename:
            return jsonify({'success': False, 'msg': '未选择文件'})

        safe_title = _resource_dir_for_session(title)
        if not safe_title:
            return jsonify({'success': False, 'msg': '资源标题不合法（清洗后为空或与系统目录重名）'}), 400
        base_dir = os.path.join(_BASE, 'static', 'uploads', safe_title)
        if subfolder:
            subfolder_clean = secure_filename_with_unicode(subfolder)
            resource_dir = os.path.join(base_dir, subfolder_clean)
        else:
            resource_dir = base_dir
        os.makedirs(resource_dir, exist_ok=True)

        saved_files = []
        resource_dir_real = os.path.realpath(resource_dir)
        for file in files:
            if file and file.filename:
                raw_path = file.filename.replace('\\', '/').lstrip('/')
                filepath = raw_path
                if '..' in filepath.split('/'):
                    return jsonify({'success': False, 'msg': '非法文件名'}), 400
                # 课件目录需内联 HTML（功能要求），仅拒绝可执行类型与超大文件：
                # 被攻破的管理员账号无法借此托管可执行载荷/撑爆磁盘
                reject_msg = _resource_reject_message(filepath)
                if reject_msg:
                    return jsonify({'success': False, 'msg': reject_msg}), 400
                _size_ok, _err = _check_upload_file_size(file, 200 * 1024 * 1024)
                if not _size_ok:
                    return jsonify({'success': False, 'msg': _err}), 413
                dest_path = os.path.realpath(os.path.join(resource_dir, filepath))
                if dest_path == resource_dir_real or not dest_path.startswith(resource_dir_real + os.sep):
                    return jsonify({'success': False, 'msg': '非法文件路径'}), 400
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(filepath)
                    counter = 1
                    while os.path.exists(dest_path):
                        new_name = f'{base} ({counter}){ext}'
                        dest_path = os.path.realpath(os.path.join(resource_dir, new_name))
                        if dest_path == resource_dir_real or not dest_path.startswith(resource_dir_real + os.sep):
                            return jsonify({'success': False, 'msg': '非法文件路径'}), 400
                        counter += 1
                    filepath = new_name
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                file.save(dest_path)
                if subfolder:
                    rel_path = os.path.join(subfolder_clean, filepath).replace('\\', '/')
                else:
                    rel_path = filepath
                saved_files.append(rel_path)
        if not saved_files:
            return jsonify({'success': False, 'msg': '没有保存任何文件'})

        # 失效文件清单与 /study 聚合缓存（分块上传后编辑页立即可见新文件）
        _invalidate_study_caches(safe_title)

        return jsonify({
            'success': True,
            'files': saved_files,
            'directory': safe_title,
            'title': title,
            'msg': f'成功上传{len(saved_files)}个文件'
        })
    except Exception as e:
        current_app.logger.error(f'文件上传失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'msg': '上传失败'})


def _stale_merging_flag(flag_path, max_age=600):
    """合并标记是否陈旧（进程崩溃残留）：按 mtime 判龄，超时视为可移除。"""
    try:
        return time.time() - os.path.getmtime(flag_path) > max_age
    except OSError:
        return False


@resources_bp.route('/admin/resources/chunk_status', methods=['GET'])
@teacher_edit_required
def chunk_status():
    """查询分块上传任务状态（断点续传支持）。

    返回已接收的分块索引；前端据此跳过已传块，网络中断后重新上传
    同一文件时从中断处继续，无需整文件重传。分块 TTL 24h（chunk_upload
    内顺带清理），超时后任务目录被清，返回空列表从头传即可。
    若任务目录不存在但目标文件已存在（此前已合并完成），返回
    merged=true，前端直接跳过该文件，避免重传产生"文件名 (1)"重复文件。
    """
    upload_id = request.args.get('upload_id', '')
    filename = request.args.get('filename', '')
    title = request.args.get('title', '')
    try:
        total_chunks = int(request.args.get('total_chunks', 0))
    except (TypeError, ValueError):
        total_chunks = 0

    safe_upload_id = secure_filename_with_unicode(upload_id)
    if not safe_upload_id:
        return jsonify({'success': False, 'msg': '非法上传ID'}), 400
    tmp_name = hashlib.sha256(filename.encode('utf-8', errors='ignore')).hexdigest()
    chunks_root = os.path.realpath(os.path.join(_BASE, 'static', 'chunks'))
    tmp_dir = os.path.realpath(os.path.join(chunks_root, safe_upload_id, tmp_name))
    if tmp_dir != chunks_root and not tmp_dir.startswith(chunks_root + os.sep):
        return jsonify({'success': False, 'msg': '非法上传路径'}), 400

    received = []
    if os.path.isdir(tmp_dir):
        try:
            received = sorted(
                int(f) for f in os.listdir(tmp_dir)
                if f.isdigit() and 0 <= int(f) < total_chunks
            )
        except (ValueError, OSError):
            received = []

    # 目标文件是否已存在（仅当任务目录不存在时才有意义：合并完成后
    # 服务端会删除任务目录）
    merged = False
    completed_filename = None
    if not received and title and filename:
        safe_title = _resource_dir_for_session(title)
        if safe_title:
            resource_root = os.path.realpath(
                os.path.join(_BASE, 'static', 'uploads', safe_title))
            base_dir = resource_root
            subfolder = request.args.get('subfolder', '').strip()
            if subfolder:
                subfolder_clean = secure_filename_with_unicode(subfolder)
                base_dir = os.path.join(base_dir, subfolder_clean)
            file_path = filename.replace('\\', '/').lstrip('/')
            if '..' not in file_path.split('/'):
                dest_path = os.path.realpath(os.path.join(base_dir, file_path))
                if dest_path.startswith(resource_root + os.sep):
                    merged = os.path.isfile(dest_path)
                    if merged:
                        completed_filename = os.path.relpath(
                            dest_path, resource_root).replace('\\', '/')

    return jsonify({'success': True, 'received': received, 'merged': merged,
                    'filename': completed_filename})


@resources_bp.route('/admin/resources/chunk_upload', methods=['POST'])
@teacher_edit_required
def chunk_upload():
    """分块上传接口 - 用于大文件上传"""
    try:
        chunk = request.files.get('chunk')
        if not chunk:
            return jsonify({'success': False, 'msg': '无分块数据'}), 400

        chunk_index = int(request.form.get('chunk_index', 0))
        total_chunks = int(request.form.get('total_chunks', 1))
        filename = request.form.get('filename', 'unnamed')
        upload_id = request.form.get('upload_id', 'default')
        title = request.form.get('title', 'default')
        subfolder = request.form.get('subfolder', '').strip()
        if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks or total_chunks > 10000:
            return jsonify({'success': False, 'msg': '无效的分块参数'}), 400
        if not _resource_dir_name(title):
            return jsonify({'success': False, 'msg': '资源标题不合法（清洗后为空或与系统目录重名）'}), 400

        # 在写入第一个分块前就校验文件名与扩展名：此前只在最后一块合并时
        # 检查，文件夹里混入 exe/bat 等文件会把整份内容传完（进度 99%）
        # 才失败，用户既拿不到具体文件名又白耗流量。
        file_path = (filename or '').replace('\\', '/').lstrip('/')
        if not file_path or '..' in file_path.split('/'):
            return jsonify({'success': False, 'msg': '非法文件名'}), 400
        reject_msg = _resource_reject_message(file_path)
        if reject_msg:
            return jsonify({'success': False, 'msg': reject_msg}), 400

        safe_upload_id = secure_filename_with_unicode(upload_id) or 'default'
        tmp_name = hashlib.sha256(filename.encode('utf-8', errors='ignore')).hexdigest()
        chunks_root = os.path.realpath(os.path.join(_BASE, 'static', 'chunks'))
        tmp_dir = os.path.realpath(os.path.join(chunks_root, safe_upload_id, tmp_name))
        if tmp_dir != chunks_root and not tmp_dir.startswith(chunks_root + os.sep):
            return jsonify({'success': False, 'msg': '非法上传路径'}), 400
        os.makedirs(tmp_dir, exist_ok=True)
        # 顺带清理该上传任务下超时未完成的分块（TTL 24h），
        # 防止中断的上传临时文件永久占用磁盘
        try:
            now = time.time()
            task_dir = os.path.join(chunks_root, safe_upload_id)
            if os.path.isdir(task_dir):
                for entry in os.listdir(task_dir):
                    entry_path = os.path.join(task_dir, entry)
                    if os.path.isdir(entry_path) and now - os.path.getmtime(entry_path) > 24 * 3600:
                        shutil.rmtree(entry_path, ignore_errors=True)
        except OSError:
            pass
        # 合并进行中（.merging 标记存在）时拒绝新块写入：此前标记只在
        # 合并权获取时才检查，合并期间的重复块请求会先 chunk.save 覆盖
        # 正在被流式读取的分块文件——异常客户端可致合并文件损坏。
        # 陈旧标记（进程崩溃残留）按 mtime 判龄移除，允许重新合并。
        merge_flag = os.path.join(tmp_dir, '.merging')
        if os.path.exists(merge_flag):
            if _stale_merging_flag(merge_flag):
                try:
                    os.remove(merge_flag)
                except OSError:
                    pass
            else:
                return jsonify({'success': False,
                                'msg': '文件正在合并中，请稍后重试'}), 409
        chunk.save(os.path.join(tmp_dir, str(chunk_index)))

        # 支持乱序分块：任意一个请求补齐全部分块后立即合并。
        if all_chunks_present(tmp_dir, total_chunks):
            # 确定目标目录（入口已校验标题可用）
            safe_title = _resource_dir_for_session(title)
            base_dir = os.path.join(_BASE, 'static', 'uploads', safe_title)
            if subfolder:
                subfolder_clean = secure_filename_with_unicode(subfolder)
                resource_dir = os.path.join(base_dir, subfolder_clean)
            else:
                resource_dir = base_dir
            os.makedirs(resource_dir, exist_ok=True)

            # 处理文件路径（支持子目录）—— 严格白名单：拒绝 .. 与绝对路径
            # （入口已提前校验，这里保留纵深防御）
            file_path = (filename or '').replace('\\', '/').lstrip('/')
            if not file_path or '..' in file_path.split('/'):
                return jsonify({'success': False, 'msg': '非法文件名'}), 400
            # 可执行扩展名黑名单与 upload_resource_files 对齐（纵深防御：
            # 分块路径同样拒绝 exe/bat/ps1 等载荷——课件目录需内联 HTML，
            # 故不拒 html/htm/svg/js）
            reject_msg = _resource_reject_message(file_path)
            if reject_msg:
                return jsonify({'success': False, 'msg': reject_msg}), 400
            resource_dir_real = os.path.realpath(resource_dir)
            dest_path = os.path.realpath(os.path.join(resource_dir, file_path))
            if dest_path == resource_dir_real or not dest_path.startswith(resource_dir_real + os.sep):
                return jsonify({'success': False, 'msg': '非法文件路径'}), 400

            # 如果文件已存在，添加序号
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(file_path)
                counter = 1
                while os.path.exists(dest_path):
                    new_name = f'{base} ({counter}){ext}'
                    dest_path = os.path.realpath(os.path.join(resource_dir, new_name))
                    if dest_path == resource_dir_real or not dest_path.startswith(resource_dir_real + os.sep):
                        return jsonify({'success': False, 'msg': '非法文件路径'}), 400
                    counter += 1
                file_path = os.path.relpath(dest_path, resource_dir_real).replace('\\', '/')

            # 确保子目录存在
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            # 合并分块
            missing_chunks = [
                i for i in range(total_chunks)
                if not os.path.exists(os.path.join(tmp_dir, str(i)))
            ]
            if missing_chunks:
                return jsonify({'success': False, 'msg': '分块数据不完整'}), 400

            # 合并前校验分块总大小：单请求上限 2GB 不约束合并总量。
            # 上限 50GB（≈ 10000 块 × 5MB 前端块大小），覆盖超大教学
            # 资源（4K 视频等单文件 >2GB 场景），同时防恶意拼出无界文件
            # 耗尽磁盘。
            total_size = 0
            for i in range(total_chunks):
                try:
                    total_size += os.path.getsize(os.path.join(tmp_dir, str(i)))
                except OSError:
                    continue
            if total_size > MAX_RESOURCE_FILE_MERGE_BYTES:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return jsonify({'success': False,
                                'msg': f'合并文件超过 {MAX_RESOURCE_FILE_MERGE_BYTES // (1024**3)}GB 限制'}), 413

            # 并发合并保护：两个请求可能同时通过 all_chunks_present 检查后互相覆盖。
            # 用 O_EXCL 原子创建合并标记：先到者获得合并权，后到者提示稍后重试。
            # 陈旧标记（进程崩溃残留）按 mtime 判龄 10 分钟移除，避免阻塞最长 24h。
            merge_flag = os.path.join(tmp_dir, '.merging')
            try:
                if os.path.exists(merge_flag) and _stale_merging_flag(merge_flag):
                    try:
                        os.remove(merge_flag)
                    except OSError:
                        pass
                flag_fd = os.open(merge_flag, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(flag_fd)
            except OSError:
                # 标记已存在（另一请求正在合并）：客户端稍后重试即可
                return jsonify({'success': False, 'msg': '文件正在合并中，请稍后重试'}), 409

            # 合并到同目录临时文件后原子改名：直接写目标文件时，合并中途
            # 异常（磁盘满/进程中断）会在最终路径留下截断的半成品，且因
            # 「已存在→加序号」逻辑，重传会生成 `<name> (1)`，坏文件仍以原名
            # 留在资源列表里可被下载。改为先写 `<dest>.part`、成功后
            # os.replace 原子替换，异常时删除临时文件。
            tmp_out = dest_path + '.part'
            try:
                with open(tmp_out, 'wb') as outf:
                    for i in range(total_chunks):
                        chunk_path = os.path.join(tmp_dir, str(i))
                        with open(chunk_path, 'rb') as inf:
                            # 流式复制：50GB 级文件合并时不整块驻留内存
                            shutil.copyfileobj(inf, outf, 1024 * 1024)
                        # 逐块刷新合并标记 mtime：50GB 在低速盘上合并可超
                        # 10 分钟，不刷新会被并发请求按「崩溃残留」误判移除
                        # 标记并再次合并同一目标 → 两路交错写坏文件
                        try:
                            os.utime(merge_flag, None)
                        except OSError:
                            pass
                os.replace(tmp_out, dest_path)
            except Exception:
                # 合并失败：清理临时文件与标记（保留临时分块），允许客户端重试
                try:
                    if os.path.exists(tmp_out):
                        os.remove(tmp_out)
                except OSError:
                    pass
                try:
                    os.remove(merge_flag)
                except OSError:
                    pass
                raise

            # 合并完成，删除标记后再清理临时目录
            try:
                os.remove(merge_flag)
            except OSError:
                pass
            shutil.rmtree(tmp_dir, ignore_errors=True)

            # 失效缓存：合并完成的新文件立即出现在编辑页//study
            # （此前漏删，最长 5 分钟"上传成功却看不到文件"）
            _invalidate_study_caches(safe_title)

            # 返回相对路径
            if subfolder:
                rel_path = os.path.join(subfolder_clean, file_path).replace('\\', '/')
            else:
                rel_path = file_path

            return jsonify({
                'success': True,
                'msg': '文件上传完成',
                'filename': rel_path,
                'is_complete': True
            })

        return jsonify({
            'success': True,
            'msg': f'分块 {chunk_index + 1}/{total_chunks} 已接收',
            'is_complete': False
        })
    except Exception as e:
        current_app.logger.error(f'分块上传失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'msg': '上传失败'}), 500


@resources_bp.route('/admin/resources/cancel_upload/<upload_id>', methods=['POST'])
@teacher_edit_required
def cancel_upload(upload_id):
    """取消上传并清理临时文件"""
    try:
        safe_upload_id = secure_filename_with_unicode(upload_id)
        if not safe_upload_id:
            return jsonify({'success': False, 'msg': '非法上传ID'}), 400
        chunks_root = os.path.realpath(os.path.join(_BASE, 'static', 'chunks'))
        tmp_dir = os.path.realpath(os.path.join(chunks_root, safe_upload_id))
        if tmp_dir == chunks_root or not tmp_dir.startswith(chunks_root + os.sep):
            return jsonify({'success': False, 'msg': '非法上传目录'}), 400
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({'success': True, 'msg': '已取消上传'})
    except Exception as e:
        current_app.logger.error(f'取消上传失败: {str(e)}')
        return jsonify({'success': False, 'msg': '操作失败，请稍后重试'}), 500


@resources_bp.route('/admin/resources/save_with_settings', methods=['POST'])
@teacher_edit_required
def save_resource_with_settings():
    """保存资源设置 — 创建/更新资源，处理作业和权限"""
    try:
        import json as _json
        data = request.get_json()
        title = data.get('title', '').strip()
        directory = data.get('directory', '').strip()
        homepage = data.get('homepage', '').strip()
        homework = data.get('homework', [])
        permissions = data.get('permissions', {})
        delete_files = data.get('delete_files', [])
        inject_files = data.get('inject_files', [])
        if not isinstance(inject_files, list):
            inject_files = []
        subject_id = data.get('subject_id', '')

        if not title or not directory:
            return jsonify({'success': False, 'msg': '缺少必要参数'}), 400

        # 目录名经过 secure_filename_with_unicode 处理，需要再次处理以匹配实际路径；
        # 教师目录统一加 t<teacher_id>_ 前缀，避免跨教师覆盖。
        safe_directory = _resource_dir_for_session(directory)
        if not safe_directory:
            return jsonify({'success': False, 'msg': '目录不存在'}), 404
        dir_path = os.path.join(_BASE, 'static', 'uploads', safe_directory)
        if not os.path.isdir(dir_path):
            return jsonify({'success': False, 'msg': '目录不存在'}), 404
        dir_path_real = os.path.realpath(dir_path)

        # 删除标记为删除的文件
        for df in delete_files:
            safe_rel = (df or '').replace('\\', '/').lstrip('/')
            if '..' in safe_rel.split('/'):
                continue
            target = os.path.realpath(os.path.join(dir_path_real, safe_rel))
            if target != dir_path_real and target.startswith(dir_path_real + os.sep) and os.path.isfile(target):
                os.remove(target)

        # 列举剩余文件
        remaining_files = []
        for root, _, filenames in os.walk(dir_path):
            for fn in filenames:
                if not fn.startswith('.'):
                    rel = os.path.relpath(os.path.join(root, fn), dir_path).replace('\\', '/')
                    # 课堂衍生文件与备份不作为主页兜底（与文件卡片过滤口径一致）
                    if rel.endswith('.pptist.json') or rel.endswith('.bak') or (
                            (rel.startswith('mindmap-') or rel.startswith('flow-')) and rel.endswith('.json')):
                        continue
                    remaining_files.append(rel)
        remaining_files = sorted(remaining_files)

        if not remaining_files:
            return jsonify({'success': False, 'msg': '没有剩余文件，请上传新文件'}), 400

        # 确定资源URL（使用 safe_directory）
        if homepage and homepage in remaining_files:
            resource_url = f'/static/uploads/{safe_directory}/{homepage}'
        else:
            resource_url = f'/static/uploads/{safe_directory}/{remaining_files[0]}'

        # 主页文件不能同时是作业
        if homepage and homepage in homework:
            homework.remove(homepage)

        # 保存作业和权限为JSON
        homework_json = _json.dumps(homework, ensure_ascii=False)
        permissions_json = _json.dumps(permissions, ensure_ascii=False)

        sid = parse_int(subject_id)
        teacher_creator = _session_teacher_id()
        if teacher_creator:
            if not sid or not teacher_subject_allowed(teacher_creator, sid):
                return jsonify({'success': False,
                                'msg': '请选择你所属学科后再保存资源'}), 403
        show_student = data.get('show_in_student', True)
        show_classroom = data.get('show_in_classroom', True)
        allow_related = bool(data.get('allow_related_files', False))
        quiz_mode = data.get('quiz_mode', 'inject')

        if teacher_creator:
            res = Resource.query.filter_by(
                title=title, creator_teacher_id=teacher_creator
            ).order_by(Resource.id.desc()).first()
        else:
            res = Resource.query.filter_by(title=title).order_by(Resource.id.desc()).first()
        if res and not teacher_can_edit(res, teacher_creator,
                                        bool(session.get('is_admin'))):
            return jsonify({'success': False, 'msg': '无权修改该资源'}), 403
        if res and res.subject_id != sid:
            # 跨学科同名资源安全防护：按 title 匹配到的候选资源属于其他学科时，
            # 覆盖会破坏对方资源的 URL/作业/权限配置（且目录按标题命名，同名目录
            # 本身会互相干扰）。此处改为新建独立资源记录而非覆盖。
            current_app.logger.warning(
                f'同名资源跨学科上传：标题="{title}" 已属学科 {res.subject_id}，'
                f'本次上传学科 {sid}，已新建独立资源而非覆盖')
            res = None
        if res:
            res.url = resource_url
            res.subject_id = sid
            res.homework_files = homework_json
            res.file_permissions = permissions_json
            res.show_in_student = show_student
            res.show_in_classroom = show_classroom
            res.allow_related_files = allow_related
            res.quiz_mode = quiz_mode
        else:
            res = Resource(title=title, url=resource_url, subject_id=sid,
                           homework_files=homework_json,
                           file_permissions=permissions_json,
                           show_in_student=show_student,
                           show_in_classroom=show_classroom,
                           allow_related_files=allow_related,
                           quiz_mode=quiz_mode,
                           creator_type='teacher' if teacher_creator else 'admin',
                           creator_teacher_id=teacher_creator,
                           creator_name=(session.get('teacher_name') if teacher_creator
                                         else (session.get('admin_name') or '管理员')))
            db.session.add(res)

        log = Log(
            user_id=0, user_type='admin',
            action='创建/更新学习资源',
            detail=f'标题: {title}, 作业: {len(homework)}个, 文件: {len(remaining_files)}个',
            time=datetime.now()
        )
        db.session.add(log)
        db.session.commit()
        _invalidate_study_caches(safe_directory)

        pending = []
        if quiz_mode == 'inject':
            for fn in inject_files:
                safe_rel = (fn or '').replace('\\', '/').lstrip('/')
                if ('..' in safe_rel.split('/') or
                        not safe_rel.lower().endswith(('.html', '.htm'))):
                    continue
                if safe_rel in remaining_files:
                    pending.append(safe_rel)
        pending = sorted(set(pending))
        res.quiz_pending_files = _json.dumps(pending, ensure_ascii=False) if pending else None
        if pending:
            res.quiz_inject_state = 'pending'
        else:
            res.quiz_inject_state = 'verified' if res.injected else 'none'
        db.session.commit()

        msg = f'资源 "{title}" 保存成功（{len(remaining_files)}个文件，{len(homework)}个作业）'
        redirect_url = (url_for('resources.teacher_resource_library')
                        if teacher_creator else
                        url_for('resources.admin_resources',
                                created='true', title=title))
        if pending:
            msg += f'；请完成 {len(pending)} 个 HTML 文件的注入检测后应用采集脚本'
            redirect_url = url_for('resources.resource_quiz_check', res_id=res.id)
        return jsonify({
            'success': True,
            'msg': msg,
            'inject': {'injected': 0, 'skipped': 0, 'failed': 0},
            'pending': pending,
            'redirect': redirect_url
        })
    except Exception as e:
        current_app.logger.error(f'保存资源设置失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'msg': '保存失败'}), 500


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check')
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check')
@teacher_edit_required
def resource_quiz_check(res_id):
    """注入前检测页：列出待检测文件，试运行通过后按文件应用。"""
    res = _quiz_check_resource(res_id)
    pending = []
    for rel in _quiz_pending_files(res):
        norm, fp = _quiz_rel_abs(res, rel)
        if norm:
            pending.append({'name': norm, 'injected': is_html_injected(fp)})
    return render_template(
        'resource_quiz_check.html',
        res=res, pending=pending,
        inject_state=res.quiz_inject_state or 'none',
        back_url=(url_for('resources.admin_resources')
                  if session.get('is_admin')
                  else url_for('resources.teacher_resource_library')),
        start_url=url_for('resources.resource_quiz_check_start', res_id=res.id),
        apply_url=url_for('resources.resource_quiz_check_apply', res_id=res.id),
        status_url=url_for('resources.resource_quiz_check_status',
                           res_id=res.id, token='__TOKEN__'),
        report_url=url_for('resources.resource_quiz_check_report',
                           res_id=res.id, token='__TOKEN__'),
        preview_url=url_for('resources.resource_quiz_check_preview',
                            res_id=res.id, token='__TOKEN__'),
    )


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check/start',
                    methods=['POST'])
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check/start',
                    methods=['POST'])
@teacher_edit_required
def resource_quiz_check_start(res_id):
    """生成临时演练页（不修改原文件、不写成绩）。"""
    res = _quiz_check_resource(res_id)
    if res.quiz_mode != 'inject':
        return jsonify({'success': False, 'msg': '该资源未启用注入采集'}), 400
    data = json_body_or_empty()
    rel, _fp = _quiz_rel_abs(res, data.get('file'))
    if not rel or rel not in _quiz_pending_files(res):
        return jsonify({'success': False, 'msg': '文件不在待检测列表'}), 400
    _quiz_check_cleanup()
    token = uuid.uuid4().hex
    content = _build_quiz_check_html(res, rel, token)
    if content is None:
        return jsonify({'success': False,
                        'msg': '文件不存在、不是 HTML 或超过 20MB'}), 400
    with open(_quiz_check_html_path(token), 'w', encoding='utf-8') as f:
        f.write(content)
    meta = {
        'created': time.time(), 'resource_id': res.id,
        'source_file': rel, 'status': 'testing', 'reason': '等待试运行',
        'payload': None,
    }
    with open(_quiz_check_meta_path(token), 'w', encoding='utf-8') as f:
        _json.dump(meta, f, ensure_ascii=False)
    return jsonify({
        'success': True, 'token': token,
        'preview_url': url_for('resources.resource_quiz_check_preview',
                               res_id=res.id, token=token),
        'status_url': url_for('resources.resource_quiz_check_status',
                              res_id=res.id, token=token),
    })


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check/preview/<token>')
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check/preview/<token>')
@teacher_edit_required
def resource_quiz_check_preview(res_id, token):
    """提供临时演练页；只允许当前资源编辑者读取。"""
    res = _quiz_check_resource(res_id)
    meta = _quiz_check_meta(token)
    if not meta or int(meta.get('resource_id') or 0) != res.id:
        abort(404)
    try:
        with open(_quiz_check_html_path(token), encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except OSError:
        abort(404)
    resp = Response(content, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check/report/<token>',
                    methods=['POST'])
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check/report/<token>',
                    methods=['POST'])
@teacher_edit_required
def resource_quiz_check_report(res_id, token):
    """接收演练页回传的试答数据；仅保存到临时检测文件。"""
    res = _quiz_check_resource(res_id)
    meta = _quiz_check_meta(token)
    if not meta or int(meta.get('resource_id') or 0) != res.id:
        return jsonify({'success': False, 'msg': '检测会话不存在或已过期'}), 404
    if request.content_length and request.content_length > 2 * 1024 * 1024:
        return jsonify({'success': False, 'msg': '检测数据过大'}), 413
    payload = json_body_or_empty()
    if not isinstance(payload, dict):
        return jsonify({'success': False, 'msg': '检测数据格式无效'}), 400
    # 服务端固定资源与文件，避免演练页伪造到其他资源
    payload['resource_id'] = res.id
    payload['source_file'] = meta.get('source_file')
    from app.services.quiz_analytics import normalize_questions
    try:
        questions = normalize_questions(payload.get('questions'))
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc)}), 400
    if questions is not None:
        payload['questions'] = questions
    status, reason = _quiz_dry_run_status(payload)
    if questions:
        option_count = sum(bool(question['options']) for question in questions)
        reason += f'；逐题 {len(questions)} 题（{option_count} 题含选项）'
    meta.update({'status': status, 'reason': reason,
                 'payload': payload, 'updated': time.time()})
    with open(_quiz_check_meta_path(token), 'w', encoding='utf-8') as f:
        _json.dump(meta, f, ensure_ascii=False)
    return jsonify({'success': True, 'status': status, 'reason': reason})


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check/status/<token>')
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check/status/<token>')
@teacher_edit_required
def resource_quiz_check_status(res_id, token):
    res = _quiz_check_resource(res_id)
    meta = _quiz_check_meta(token)
    if not meta or int(meta.get('resource_id') or 0) != res.id:
        return jsonify({'success': False, 'msg': '检测会话不存在或已过期'}), 404
    return jsonify({
        'success': True,
        'status': meta.get('status') or 'testing',
        'reason': meta.get('reason') or '',
        'source_file': meta.get('source_file') or '',
        'payload': meta.get('payload'),
    })


@resources_bp.route('/teacher/resources/<int:res_id>/quiz-check/apply',
                    methods=['POST'])
@resources_bp.route('/admin/resources/<int:res_id>/quiz-check/apply',
                    methods=['POST'])
@teacher_edit_required
def resource_quiz_check_apply(res_id):
    """仅将通过/（确认后的）部分通过文件写入正式注入。"""
    res = _quiz_check_resource(res_id)
    if res.quiz_mode != 'inject':
        return jsonify({'success': False, 'msg': '该资源未启用注入采集'}), 400
    data = json_body_or_empty()
    tests = data.get('tests')
    if not isinstance(tests, list) or not tests:
        return jsonify({'success': False, 'msg': '请选择已通过检测的文件'}), 400
    pending = set(_quiz_pending_files(res))
    results = []
    applied = []
    last_backup = None
    for item in tests[:50]:
        if not isinstance(item, dict):
            continue
        rel, fp = _quiz_rel_abs(res, item.get('file'))
        token = str(item.get('token') or '')
        if not rel or rel not in pending:
            results.append({'file': item.get('file') or '', 'success': False,
                            'msg': '文件不在待检测列表'})
            continue
        meta = _quiz_check_meta(token)
        if not meta or int(meta.get('resource_id') or 0) != res.id:
            results.append({'file': rel, 'success': False,
                            'msg': '检测会话已失效（可能已过期或服务更新/重启），请重新检测'})
            continue
        if meta.get('source_file') != rel:
            results.append({'file': rel, 'success': False,
                            'msg': '检测会话与文件不匹配，请重新检测'})
            continue
        status = meta.get('status')
        # 「仅答案」的二次确认在前端完成；服务端不再额外要求 allow_partial，
        # 避免前端版本/缓存差异导致教师确认后仍被拒绝。
        if status not in ('pass', 'partial'):
            results.append({'file': rel, 'success': False,
                            'msg': f'检测状态为 {status or "未知"}，不能应用'})
            continue
        already = is_html_injected(fp)
        inject_error = ''
        try:
            changed = inject_quiz_collector(fp, res.id, rel)
        except Exception as exc:
            inject_error = str(exc)
            current_app.logger.warning(
                '应用测验采集器失败: %s (%s)', rel, exc, exc_info=True)
            changed = False
        if changed or already:
            applied.append(rel)
            pending.discard(rel)
            _quiz_check_remove(token)
            if os.path.exists(fp + '.bak'):
                last_backup = fp + '.bak'
            results.append({'file': rel, 'success': True,
                            'partial': status == 'partial',
                            'msg': '已更新注入' if changed else '已存在采集器'})
        else:
            if not os.access(fp, os.W_OK):
                msg = '文件不可写：服务运行账号缺少该文件的写权限'
            elif inject_error:
                msg = '写入失败：' + inject_error[:200]
            else:
                msg = '写入失败（文件未产生变更）'
            results.append({'file': rel, 'success': False, 'msg': msg})

    res.quiz_pending_files = _json.dumps(sorted(pending), ensure_ascii=False)
    if applied:
        res.injected = True
        if last_backup:
            res.backup_path = last_backup
    if pending:
        res.quiz_inject_state = 'partial' if applied else 'pending'
    else:
        res.quiz_inject_state = 'verified' if res.injected else 'none'
    db.session.add(Log(
        user_id=0, user_type='admin', action='应用测验采集器',
        detail=f'资源: {res.title}, 成功: {len(applied)}, 待处理: {len(pending)}',
        time=datetime.now()))
    db.session.commit()
    _invalidate_quiz_resource(res)
    return jsonify({
        'success': bool(applied),
        'msg': (f'已应用 {len(applied)} 个文件' if applied
                else '没有文件被应用'),
        'results': results,
        'pending': sorted(pending),
        'state': res.quiz_inject_state,
    })


@resources_bp.route('/admin/resources/download/<int:res_id>')
@admin_login_required
def download_resource_zip(res_id):
    """下载整个资源目录为ZIP"""
    resource = db.get_or_404(Resource, res_id)
    if not resource.url or not resource.url.startswith('/static/uploads/'):
        return '无可下载文件', 400
    url_path = resource.url.replace('/static/uploads/', '', 1)
    dir_name = url_path.split('/')[0]
    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    dir_path = os.path.realpath(os.path.join(uploads_root, dir_name))
    if dir_path == uploads_root or not dir_path.startswith(uploads_root + os.sep):
        return '非法目录', 400
    if not os.path.isdir(dir_path):
        return '目录不存在', 404
    # 磁盘空间保护：打包是磁盘→磁盘复制，内存无压力，但需确保剩余
    # 空间足够容纳 ZIP（资源目录可含单文件 >2GB 的教学资源，不设
    # 硬编码大小上限）
    total_size = sum(
        os.path.getsize(os.path.join(root, fn))
        for root, _, filenames in os.walk(dir_path)
        for fn in filenames if not fn.startswith('.')
    )
    try:
        free_bytes = shutil.disk_usage(tempfile.gettempdir())[2]
    except OSError:
        free_bytes = 0
    if free_bytes and total_size > free_bytes:
        return (f'磁盘空间不足（打包需要约 {total_size // (1024 ** 3)}GB，'
                f'可用 {free_bytes // (1024 ** 3)}GB）'), 400
    # 打包到磁盘临时文件而非内存（大资源 BytesIO 峰值 ≈ 目录大小 × 2，有 OOM 风险）
    from app.utils import send_temp_zip

    def _build(zf):
        for root, _, filenames in os.walk(dir_path):
            for fn in filenames:
                if not fn.startswith('.'):
                    full = os.path.join(root, fn)
                    zf.write(full, os.path.relpath(full, dir_path))
    safe = re.sub(r'[^\w一-鿿-]', '_', resource.title)
    return send_temp_zip(_build, f'{safe}.zip')


@resources_bp.route('/admin/resources/list_uploaded_files', methods=['GET'])
@admin_login_required
def list_uploaded_files():
    """列出指定目录下的所有文件"""
    directory = request.args.get('directory')
    if not directory:
        return jsonify({'success': False, 'msg': '缺少目录参数'}), 400
    try:
        safe_dir = _resource_dir_name(directory)
        if not safe_dir:
            return jsonify({'success': False, 'msg': '指定的目录不存在'}), 404
        dir_path = os.path.join(_BASE, 'static', 'uploads', safe_dir)
        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            return jsonify({'success': False, 'msg': '指定的目录不存在'}), 404
        files = []
        for root, _, filenames in os.walk(dir_path):
            rel_root = os.path.relpath(root, dir_path)
            for filename in filenames:
                if not filename.startswith('.'):
                    rel_path = os.path.normpath(os.path.join(rel_root, filename))
                    if rel_path == '.':
                        rel_path = filename
                    files.append(rel_path)
        return jsonify({'success': True, 'files': sorted(files)})
    except Exception as e:
        current_app.logger.error(f'获取文件列表失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'msg': '获取文件列表失败'}), 500


@resources_bp.route('/api/resource_quiz/submit', methods=['POST'])
@login_required
def resource_quiz_submit():
    """接收静态网页中的答题数据"""
    import json as _json
    import math
    try:
        if request.content_length and request.content_length > 4 * 1024 * 1024:
            return jsonify({'success': False, 'msg': '答题数据过大'}), 413
        data = json_body_or_empty()
        student_id = session.get('student_id')
        if not student_id:
            return jsonify({'success': False, 'msg': '未登录'}), 401

        resource_id = data.get('resource_id')
        if not resource_id:
            return jsonify({'success': False, 'msg': '缺少资源ID'}), 400

        try:
            resource_id = int(resource_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'msg': '无效的资源ID'}), 400

        resource = db.session.get(Resource, resource_id)
        if not resource:
            return jsonify({'success': False, 'msg': '资源不存在'}), 404
        if _student_resource_out_of_scope(resource):
            return jsonify({'success': False, 'msg': '无权提交该资源的答题数据'}), 403
        # 未启用采集的模式（none/runtime——runtime 已在 sandbox 隔离下不可用）
        # 拒绝接收自报成绩
        if (resource.quiz_mode or 'inject') in ('none', 'runtime'):
            return jsonify({'success': False, 'msg': '该资源未启用成绩采集'}), 403

        source_file, quiz_key, source_err = _quiz_source_file_info(
            resource, data.get('source_file'))
        if source_err:
            return jsonify({'success': False, 'msg': source_err}), 400

        quiz_name = data.get('quiz_name', '')
        if not isinstance(quiz_name, str):
            return jsonify({'success': False, 'msg': '测验名称格式无效'}), 400
        # 按 UTF-8 字节截断（码点截断可能切断 emoji 等 astral 字符产生
        # 孤立代理项，提交时 UnicodeEncodeError → 500）
        quiz_name = (quiz_name or resource.title or '').encode('utf-8')[:200].decode('utf-8', errors='ignore')
        answers = _json.dumps(data.get('answers', {}), ensure_ascii=False)
        scores_data = data.get('scores')
        scores = _json.dumps(scores_data, ensure_ascii=False) if scores_data else None
        if len(answers.encode('utf-8')) > 1024 * 1024 or (scores and len(scores.encode('utf-8')) > 1024 * 1024):
            return jsonify({'success': False, 'msg': '答题数据过大'}), 413
        from app.services.quiz_analytics import normalize_questions
        try:
            questions = normalize_questions(data.get('questions'))
        except ValueError as exc:
            return jsonify({'success': False, 'msg': str(exc)}), 400
        question_details = (_json.dumps(questions, ensure_ascii=False)
                            if questions is not None else None)
        adapter_version = 3 if questions is not None else None

        # 测验分数由客户端自报（判分逻辑在资源文件内），服务端无法重判，
        # 此处做防御性校验：收紧分数上限、校验分数明细与总分一致，
        # 防止直接伪造满分/离谱分数污染教师端统计。
        def optional_number(name, limit=100_000):
            value = data.get(name)
            if value is None:
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                raise ValueError(f'{name} 格式无效')
            if not math.isfinite(parsed) or parsed < 0 or parsed > limit:
                raise ValueError(f'{name} 超出允许范围')
            return parsed

        try:
            total_score = optional_number('total_score')
            max_score = optional_number('max_score')
            duration_value = optional_number('duration', limit=86_400)  # 时长上限 24 小时
        except ValueError as exc:
            return jsonify({'success': False, 'msg': str(exc)}), 400
        if total_score is not None and max_score is not None and total_score > max_score:
            return jsonify({'success': False, 'msg': '总分不能超过满分'}), 400
        # 分数明细与总分一致性校验（容差 0.01）：明细缺失时跳过（兼容旧客户端）
        if scores_data and total_score is not None:
            if isinstance(scores_data, dict):
                try:
                    detail_sum = sum(float(v) for v in scores_data.values() if isinstance(v, (int, float)))
                    if abs(detail_sum - total_score) > 0.01:
                        return jsonify({'success': False, 'msg': '分数明细与总分不一致'}), 400
                except (TypeError, ValueError):
                    pass
        duration = int(duration_value) if duration_value is not None else None

        # ── 客户端自报结果的扩展形态（v5.0.0）──
        # 1) 纯等级/证书测验（无分数）：grade 字段记录等级
        # 2) "答对题数/总题数"式测验：correct_count/question_count 记录
        # 等级归一化为中文（优秀/良好/合格/不合格），兼容中英文输入；
        # 未提供等级时按 total/max 百分比推导（≥90/≥80/≥60）。
        grade = None
        raw_grade = data.get('grade') or data.get('level') or data.get('certificate')
        if raw_grade is not None:
            grade_map = {
                '优秀': '优秀', 'excellent': '优秀', 'a': '优秀', 's': '优秀',
                '良好': '良好', 'good': '良好', 'b': '良好',
                '合格': '合格', 'pass': '合格', '及格': '合格', 'c': '合格',
                '不合格': '不合格', 'fail': '不合格', '不及格': '不合格', 'd': '不合格',
            }
            grade = grade_map.get(str(raw_grade).strip().lower())
            if grade is None:
                # 白名单外等级直接拒绝：此前回退原样截断落库，任意字符串
                # 可写入教师端视图（存储型 XSS 隐患面 + 图表统计口径污染）
                return jsonify({'success': False,
                                'msg': '等级格式无效（仅支持：优秀/良好/合格/不合格）'}), 400
        elif total_score is not None and max_score and max_score > 0:
            pct = total_score / max_score * 100
            grade = '优秀' if pct >= 90 else ('良好' if pct >= 80 else
                                              ('合格' if pct >= 60 else '不合格'))

        def optional_int(name, limit=100_000):
            value = data.get(name)
            if value is None:
                return None
            try:
                fval = float(value)
                # 非有限数（inf/NaN）拒绝：int(inf) 抛 OverflowError → 500
                if not math.isfinite(fval):
                    raise ValueError(f'{name} 格式无效')
                parsed = int(fval)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f'{name} 格式无效')
            if parsed < 0 or parsed > limit:
                raise ValueError(f'{name} 超出允许范围')
            return parsed

        try:
            correct_count = optional_int('correct_count')
            question_count = optional_int('question_count')
        except ValueError as exc:
            return jsonify({'success': False, 'msg': str(exc)}), 400
        if correct_count is not None and question_count is not None \
                and correct_count > question_count:
            return jsonify({'success': False, 'msg': '答对题数不能超过总题数'}), 400

        # 同一学生、同一资源、同一测验文件只保留最新一条：
        # 唯一约束 uq_resource_quiz_student_file 兜底并发。旧版单文件
        # 记录（quiz_key='legacy'）在首次收到带 source_file 的成绩时
        # 原地升级，避免升级后同一份测验出现两条记录。
        result = ResourceQuizResult.query.filter_by(
            student_id=student_id, resource_id=resource_id,
            quiz_key=quiz_key).first()
        if result is None and quiz_key != 'legacy':
            legacy = ResourceQuizResult.query.filter_by(
                student_id=student_id, resource_id=resource_id,
                quiz_key='legacy').first()
            if legacy is not None:
                legacy.quiz_key = quiz_key
                legacy.source_file = source_file
                result = legacy
        if result is None:
            result = ResourceQuizResult(
                student_id=student_id, resource_id=resource_id,
                quiz_key=quiz_key)
            db.session.add(result)
        result.source_file = source_file
        result.quiz_name = quiz_name
        result.answers = answers
        result.question_details = question_details
        result.adapter_version = adapter_version
        result.scores = scores
        result.total_score = total_score
        result.max_score = max_score
        result.grade = grade
        result.correct_count = correct_count
        result.question_count = question_count
        result.duration = duration
        result.submit_time = datetime.now()
        try:
            db.session.commit()
        except IntegrityError:
            # 并发兜底：唯一约束冲突时按最新提交更新（重试一次）
            db.session.rollback()
            result = ResourceQuizResult.query.filter_by(
                student_id=student_id, resource_id=resource_id,
                quiz_key=quiz_key).first()
            if result is None:
                raise
            result.source_file = source_file
            result.quiz_name = quiz_name
            result.answers = answers
            result.question_details = question_details
            result.adapter_version = adapter_version
            result.scores = scores
            result.total_score = total_score
            result.max_score = max_score
            result.grade = grade
            result.correct_count = correct_count
            result.question_count = question_count
            result.duration = duration
            result.submit_time = datetime.now()
            db.session.commit()
        # 分析页短缓存立即失效：教师提交后重新打开必须看到最新统计
        quiz_analysis_cache.invalidate_analysis(resource_id)

        return jsonify({'success': True, 'msg': '答题数据已记录'})
    except Exception as e:
        current_app.logger.error(f'保存答题数据失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'msg': '保存失败'}), 500


def _derive_quiz_grade(result):
    """推导测验等级：优先提交的 grade 字段，否则按 total/max 百分比
    （≥90 优秀 / ≥80 良好 / ≥60 合格 / 其余不合格）；无分数返回 None。"""
    if getattr(result, 'grade', None):
        return result.grade
    total = getattr(result, 'total_score', None)
    max_score = getattr(result, 'max_score', None)
    if total is None or not max_score or max_score <= 0:
        return None
    pct = total / max_score * 100
    return '优秀' if pct >= 90 else ('良好' if pct >= 80 else
                                     ('合格' if pct >= 60 else '不合格'))


def _revert_resource_injection_impl(res_id):
    """撤销测验采集器注入（从 .bak 备份还原 HTML 文件）。

    注入时为每个 HTML 文件创建 `文件.bak` 备份（inject_quiz_collector），
    本端点扫描资源目录下全部 *.bak 并逐个还原，随后清除资源的注入标记。
    校验：管理员或资源创建者；备份路径严格限定在资源目录内（防路径穿越）。
    """
    resource = db.session.get(Resource, res_id)
    if not resource:
        return jsonify({'success': False, 'msg': '资源不存在'}), 404
    if not teacher_can_edit(resource, session.get('teacher_id'),
                            bool(session.get('is_admin'))):
        return jsonify({'success': False, 'msg': '无权撤销该资源的注入'}), 403
    if not resource.url or not resource.url.startswith('/static/uploads/'):
        return jsonify({'success': False, 'msg': '该资源无本地文件目录'}), 400

    url_path = resource.url.replace('/static/uploads/', '', 1)
    dir_name = url_path.split('/')[0]
    uploads_root = os.path.realpath(os.path.join(_BASE, 'static', 'uploads'))
    dir_path = os.path.realpath(os.path.join(uploads_root, dir_name))
    if dir_path == uploads_root or not dir_path.startswith(uploads_root + os.sep):
        return jsonify({'success': False, 'msg': '非法资源目录'}), 400
    if not os.path.isdir(dir_path):
        return jsonify({'success': False, 'msg': '资源目录不存在'}), 404

    from app.utils import revert_html_injection, is_html_injected
    reverted, failed, skipped = [], [], []
    for root, _, filenames in os.walk(dir_path):
        for fn in filenames:
            if not fn.endswith('.bak'):
                continue
            bak_path = os.path.realpath(os.path.join(root, fn))
            # 备份文件必须在资源目录内（双保险）
            if bak_path == dir_path or not bak_path.startswith(dir_path + os.sep):
                continue
            target = bak_path[:-4]  # 去掉 .bak 后缀 = 原始文件
            if not os.path.isfile(target):
                # 原始文件已不存在（可能被删），备份无还原目标，跳过
                continue
            # 目标已不含采集器标记 = 此前已还原过（.bak 保留为安全网），
            # 跳过避免重复计数/误导
            if not is_html_injected(target):
                skipped.append(fn[:-4])
                continue
            ok, msg = revert_html_injection(target)
            (reverted if ok else failed).append(fn[:-4])
    if not reverted and not failed:
        if skipped:
            return jsonify({'success': True, 'msg': '无需还原（注入此前已撤销，备份保留中）',
                            'reverted': [], 'failed': [], 'skipped': skipped})
        return jsonify({'success': False, 'msg': '未找到注入备份（.bak）文件'}), 404

    if reverted:
        resource.injected = False
        resource.backup_path = None
        resource.quiz_inject_state = (
            'pending' if _quiz_pending_files(resource) else 'none')
        db.session.commit()
        cache.delete('courseware:dir_map')
        cache.delete(f'study:files:{dir_name}')

    return jsonify({
        'success': True,
        'msg': f'已还原 {len(reverted)} 个文件' +
               (f'，失败 {len(failed)} 个' if failed else '') +
               ('（未找到备份的文件跳过）' if not reverted else ''),
        'reverted': reverted,
        'failed': failed,
    })


@resources_bp.route('/admin/resources/<int:res_id>/revert-injection', methods=['POST'])
@admin_login_required
def revert_resource_injection(res_id):
    return _revert_resource_injection_impl(res_id)


@resources_bp.route('/teacher/resource-library/<int:res_id>/revert-injection',
                    methods=['POST'])
@teacher_edit_required
def teacher_revert_resource_injection(res_id):
    return _revert_resource_injection_impl(res_id)


@resources_bp.route('/admin/resources/quiz_results/<int:res_id>')
@teacher_login_required
def resource_quiz_results(res_id):
    """查看资源的测验成绩（管理员全部；教师仅本人创建的资源）"""
    resource = db.get_or_404(Resource, res_id)
    if not session.get('is_admin') and not teacher_can_edit(
            resource, session.get('teacher_id'), False):
        abort(403)
    from app.utils import paginate_query
    pagination = paginate_query(
        ResourceQuizResult.query.filter_by(resource_id=res_id).order_by(
            ResourceQuizResult.submit_time.desc()),
        default_per_page=20, max_per_page=100
    )
    results = pagination.items
    # 仅加载提交记录涉及的学生（IN 过滤），避免全表加载
    from app.models import Student
    sid_list = {r.student_id for r in results if r.student_id}
    students = {}
    if sid_list:
        students = {s.id: s for s in Student.query.filter(Student.id.in_(sid_list)).all()}
    # 分数由客户端自报（判分逻辑在资源文件内，服务端无法重判）——
    # 展示层统一打"未核实"标记，提示教师分数可被伪造，勿作为可信统计依据
    # 等级分布统计（图形化展示用）+ 每行等级（模板/CSV 共用推导函数）
    # 投影仅取推导所需 3 列：全量加载每行含 answers/scores 大 Text JSON，
    # 班级规模增长后该统计线性劣化
    all_rows = (ResourceQuizResult.query.with_entities(
        ResourceQuizResult.grade, ResourceQuizResult.total_score,
        ResourceQuizResult.max_score).filter_by(resource_id=res_id).all())
    grade_dist = {'优秀': 0, '良好': 0, '合格': 0, '不合格': 0}
    for r in all_rows:
        g = _derive_quiz_grade(r)
        if g in grade_dist:
            grade_dist[g] += 1
    grade_by_id = {r.id: _derive_quiz_grade(r) for r in results}
    return render_template('admin_quiz_results.html',
                           resource=resource, results=results, students=students,
                           pagination=pagination, client_reported=True,
                           grade_dist=grade_dist, grade_by_id=grade_by_id)


@resources_bp.route('/admin/resources/quiz_analysis/<int:res_id>')
@teacher_login_required
def resource_quiz_analysis(res_id):
    """同一资源页逐题汇总（全量记录，不受成绩列表分页影响）。"""
    resource = db.get_or_404(Resource, res_id)
    if not session.get('is_admin') and not teacher_can_edit(
            resource, session.get('teacher_id'), False):
        return jsonify({'success': False, 'msg': '无权查看该资源成绩'}), 403
    from app.services.quiz_analytics import aggregate_questions
    source_column = db.func.coalesce(ResourceQuizResult.source_file, '')
    query = ResourceQuizResult.query.filter_by(resource_id=res_id)
    page_rows = query.with_entities(
        source_column.label('source_file'),
        db.func.count(db.distinct(ResourceQuizResult.student_id)).label('student_count')
    ).group_by(source_column).order_by(db.func.max(ResourceQuizResult.submit_time).desc()).all()
    pages = [{'source_file': row.source_file, 'student_count': row.student_count}
             for row in page_rows]
    source_file = request.args.get('source_file')
    if source_file is None:
        source_file = pages[0]['source_file'] if pages else ''
    try:
        cache_seconds = int(
            current_app.config.get('QUIZ_ANALYSIS_CACHE_SECONDS', 45) or 0)
    except (TypeError, ValueError):
        cache_seconds = 45
    if cache_seconds > 0:
        cached = quiz_analysis_cache.get_analysis(res_id, source_file)
        if cached is not None:
            data = dict(cached)
            data.update({'pages': pages, 'source_file': source_file,
                         'cached': True})
            return jsonify({'success': True, 'data': data})
    results = query.filter(source_column == source_file).with_entities(
        ResourceQuizResult.student_id, ResourceQuizResult.answers,
        ResourceQuizResult.question_details,
    ).order_by(ResourceQuizResult.submit_time.desc(), ResourceQuizResult.id.desc()).yield_per(50)
    data = aggregate_questions(results)
    if cache_seconds > 0:
        quiz_analysis_cache.set_analysis(res_id, source_file, data,
                                         cache_seconds)
    data.update({'pages': pages, 'source_file': source_file})
    return jsonify({'success': True, 'data': data})


@resources_bp.route('/admin/resources/quiz_results_data/<int:res_id>')
@teacher_login_required
def resource_quiz_results_data(res_id):
    """获取资源的测验成绩数据（JSON；管理员或资源创建者）"""
    resource = db.get_or_404(Resource, res_id)
    if not session.get('is_admin') and not teacher_can_edit(
            resource, session.get('teacher_id'), False):
        return jsonify({'success': False, 'msg': '无权查看该资源成绩'}), 403
    results = ResourceQuizResult.query.filter_by(resource_id=res_id).order_by(ResourceQuizResult.submit_time.desc()).all()
    # 仅加载提交记录涉及的学生（IN 过滤），避免全表加载
    from app.models import Student
    sid_list = {r.student_id for r in results if r.student_id}
    students = {}
    if sid_list:
        students = {s.id: s for s in Student.query.filter(Student.id.in_(sid_list)).all()}
    data = []
    for r in results:
        s = students.get(r.student_id)
        data.append({
            'id': r.id,
            'student_name': s.name if s else '未知',
            'student_number': s.student_number if s else '',
            'source_file': getattr(r, 'source_file', None) or '',
            'quiz_key': getattr(r, 'quiz_key', None) or '',
            'quiz_name': r.quiz_name or '',
            'answers': r.answers,
            'scores': r.scores,
            'total_score': r.total_score,
            'max_score': r.max_score,
            'grade': _derive_quiz_grade(r),
            'correct_count': getattr(r, 'correct_count', None),
            'question_count': getattr(r, 'question_count', None),
            'duration': r.duration,
            'submit_time': r.submit_time.strftime('%Y-%m-%d %H:%M:%S') if r.submit_time else ''
        })
    return jsonify({'success': True, 'data': data})
