from datetime import datetime
import secrets
from flask import Blueprint, request, render_template, redirect, url_for, session, flash, jsonify
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, cache
from app.models import (Student, ClassroomSetting, ClassroomSession, Teacher,
                        TeachingSession, Subject, SystemConfig, Resource, Class)
from app.utils import (get_client_ip, verify_admin_account, get_local_now,
                       admin_login_blocked_seconds, admin_login_register_failure,
                       admin_login_register_success,
                       student_login_blocked_seconds, student_login_register_failure,
                       student_login_register_success,
                       teacher_login_blocked_seconds, teacher_login_register_failure,
                       teacher_login_register_success,
                       password_fingerprint, session_password_matches,
                       DEFAULT_GRADE_OPTIONS)
from app.schemas import AdminLogin, validate_form
from app.decorators import (admin_login_required, authenticated_required,
                            login_required, teacher_login_required)

auth_bp = Blueprint('auth', __name__, url_prefix='')

# 教师只读访问码（全校共享，哈希落 SystemConfig；只读会话保存哈希指纹）
TEACHER_READONLY_CODE_KEY = 'teacher_readonly_code_hash'


def _clear_teacher_session(reason='session_invalid'):
    try:
        from app.services.account_tracking import end_account_session
        end_account_session(reason)
    except Exception:
        pass
    for key in ('is_teacher', 'teacher_id', 'teacher_name', 'teacher_mode',
                'readonly_code_fp', 'pwd_fp'):
        session.pop(key, None)


def _clear_student_session(message=None, reason='session_invalid'):
    """清除学生会话；页面请求时给出失效原因，静态/API 请求保持静默。"""
    try:
        from app.services.account_tracking import end_account_session
        end_account_session(reason)
    except Exception:
        pass
    for key in ('student_id', 'student_name', 'student_class_id',
                'classroom_bound', 'pwd_fp'):
        session.pop(key, None)
    if message and not request.path.startswith(('/static/', '/api/')):
        flash(message, 'warning')


def _start_account_tracking(account_type, account_id, account_name,
                            channel='web'):
    try:
        from app.services.account_tracking import start_account_session
        return start_account_session(account_type, account_id, account_name,
                                     channel=channel)
    except Exception:
        return None

# 课堂设置缓存键 + TTL（秒）
_ACTIVE_CLASS_CACHE_KEY = 'classroom:active_class_id'
_ACTIVE_CLASS_IDS_CACHE_KEY = 'classroom:active_class_ids'
_ACTIVE_CLASS_CACHE_TTL = 5


def _get_active_class_ids():
    """当前所有处于上课状态的班级 ID（多班大屏）。

    优先使用 ClassroomSession；没有会话时回退旧 ClassroomSetting 单班字段，
    保证升级前行为和旧调用方兼容。5 秒 TTL 缓存。
    """
    val = cache.get(_ACTIVE_CLASS_IDS_CACHE_KEY)
    if val is not None:
        return set(val)
    session_ids = [
        row.class_id for row in ClassroomSession.query.filter_by(
            is_active=True).order_by(ClassroomSession.id).all()
    ]
    if not session_ids:
        setting = ClassroomSetting.query.first()
        if setting and setting.active_class_id:
            session_ids = [setting.active_class_id]
    cache.set(_ACTIVE_CLASS_IDS_CACHE_KEY, tuple(session_ids),
              timeout=_ACTIVE_CLASS_CACHE_TTL)
    return set(session_ids)


def _get_active_class_id():
    """兼容旧单班调用：返回当前上课班级 ID（无则 None，取最小 ID 保证稳定）。"""
    ids = _get_active_class_ids()
    return min(ids) if ids else None


def invalidate_active_class_cache():
    """管理端修改课堂会话后调用，立刻刷新缓存"""
    cache.delete(_ACTIVE_CLASS_CACHE_KEY)
    cache.delete(_ACTIVE_CLASS_IDS_CACHE_KEY)


def _reset_session_preserving_csrf():
    # 同一浏览器重新登录：先结束旧终端会话，且不影响同账号其他终端。
    try:
        from app.services.account_tracking import end_account_session
        end_account_session('relogin')
    except Exception:
        pass
    csrf_token = session.get('csrf_token')
    session.clear()
    if csrf_token:
        session['csrf_token'] = csrf_token


def _rotate_session():
    """登录成功后轮换会话（防会话固定）：
    优先使用 session.rotate()（Flask 3.1+ 支持）；当前环境不支持时
    退化为手动 clear 后重建（保留 CSRF token），使登录前捕获的会话失效。
    注意：必须在写入新登录身份之前调用，否则退化为 clear 会清掉身份。"""
    try:
        session.rotate()
    except AttributeError:
        _reset_session_preserving_csrf()


def _migrate_teacher_from_file():
    """兼容旧版 data/teacher_account.txt，仅迁移一次。"""
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base_dir, 'data', 'teacher_account.txt')
    migrated_path = path + '.migrated'
    if not os.path.exists(path) or os.path.exists(migrated_path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [x.strip() for x in f.read().splitlines() if x.strip()]
        if len(lines) >= 2 and not Teacher.query.filter_by(username=lines[0]).first():
            teacher = Teacher(username=lines[0], display_name=lines[0])
            teacher.set_password(lines[1])
            db.session.add(teacher)
            db.session.commit()
        os.replace(path, migrated_path)
    except Exception:
        db.session.rollback()
        current_app.logger.warning('教师旧账号文件迁移失败', exc_info=True)


@auth_bp.before_app_request
def load_student_name():
    """每请求轻量校验学生会话：
    1) 学生被删除/停用时清除会话（删除后的旧会话不再有效）；
    2) 上课班级切换不匹配时清除会话（沿用原有踢人逻辑）；
    3) 未修改初始密码（共享默认密码）时强制改密，改密成功前仅放行
       改密页/退出/静态资源，防止默认密码被冒用后长期有效。
    性能：会话校验结果缓存 10s（TTL），250 并发下每请求一次主键查询
    降为每学生最多每 10s 一次；学生被删/停用/换班后会话失效有最多
    10s 延迟，可接受（改密/禁用场景的极端窗口）。"""
    from flask import g, jsonify
    student_id = session.get('student_id')
    if not student_id:
        return
    from app.extensions import cache as _sess_cache
    check_key = f'session:check:{student_id}'
    cached = _sess_cache.get(check_key)
    if cached is not None and len(cached) == 5:
        stu_class_id, is_activated, stu_name, changed_pw, pwd_fp = cached
    else:
        student = db.session.get(Student, student_id)
        if student is None or not student.is_activated:
            _clear_student_session('账号不存在或已停用，请联系老师',
                                   reason='account_invalid')
            return
        stu_class_id, is_activated, stu_name, changed_pw, pwd_fp = (
            student.class_id, student.is_activated, student.name,
            student.has_changed_password, password_fingerprint(student.password_hash))
        _sess_cache.set(check_key, (stu_class_id, is_activated,
                                    stu_name, changed_pw, pwd_fp), timeout=10)
    if not is_activated or not session_password_matches(pwd_fp):
        # 停用，或密码已被改/重置（本人改密会同步自己会话的指纹，
        # 其余持有旧会话者——如先用共享初始密码登录的人——一并失效）
        _clear_student_session('登录状态已失效，请重新登录',
                                   reason='password_changed')
        return
    # 同步姓名/班级，避免 session 与数据库不一致（改名/换班场景）
    if session.get('student_name') != stu_name:
        session['student_name'] = stu_name
    if session.get('student_class_id') != stu_class_id:
        session['student_class_id'] = stu_class_id
    active_class_ids = _get_active_class_ids()
    bound_to_class = bool(session.get('classroom_bound'))
    if bound_to_class:
        # 学生登录时绑定当前课堂会话；一旦所有班级下课（active 集合为空）
        # 或切到其他班，下一次请求立即清除该学生会话。
        if not active_class_ids or stu_class_id not in active_class_ids:
            _clear_student_session(
                '本节课已结束或已切换班级，请等待老师重新上课',
                reason='class_ended')
            return
    else:
        if active_class_ids and stu_class_id not in active_class_ids:
            _clear_student_session(
                '本节课已结束或已切换班级，请等待老师重新上课',
                reason='class_ended')
            return
        if active_class_ids:
            # 兼容升级前已登录且当前仍在课堂中的旧会话：标记后纳入下课后失效逻辑。
            session['classroom_bound'] = True
    # 未修改初始密码：强制改密；改密成功后标记自动清除
    if not changed_pw:
        session['must_change_password'] = True
        endpoint = request.endpoint or ''
        path = request.path or ''
        # 放行：改密页、退出、静态资源
        if endpoint in ('auth.change_password', 'auth.student_logout', 'static'):
            pass
        # 放行：登录/登出类端点（其路由自身有登录校验，且必须允许未改密
        # 学生重新登录/切换账号，不能被未改密会话阻塞）。
        # 此前对 /teacher/ 与 /admin/ 全路径放行面过宽——学生可访问管理端
        # 登录页暴露管理入口存在性；收窄为具体端点，其余管理路径交由
        # admin_login_required/teacher_login_required 拦截。
        elif path.startswith('/api/auth/') or path.startswith('/api/heartbeat') or \
                path.startswith('/teacher/login') or path == '/teacher/logout' or \
                path.startswith('/admin/login') or path == '/admin/logout':
            pass
        else:
            # 学生业务路径：API/考试返回 JSON 提示，普通页面重定向到改密页
            if path.startswith('/api/') or path.startswith('/exam/'):
                return jsonify({'success': False, 'message': '请先修改初始密码', 'code': 403}), 403
            return redirect(url_for('auth.change_password'))
    else:
        session.pop('must_change_password', None)
    g.student_name = stu_name


@auth_bp.before_app_request
def load_admin():
    """每请求轻量校验管理员会话（表账号）：停用/删除后旧会话即时失效
    （对标 load_teacher 的 10s TTL 缓存校验）——被停用账号无法继续操作
    管理功能，也无法在停用页自行重新启用。
    """
    if not session.get('is_admin'):
        return
    account_id = session.get('admin_account_id')
    if not account_id:
        return  # 文件账号登录无表记录，不做校验
    from app.extensions import cache as _sess_cache
    check_key = f'session:admin:{account_id}'
    cached = _sess_cache.get(check_key)
    if not isinstance(cached, tuple):
        from app.models import AdminAccount as _AA
        account = db.session.get(_AA, account_id)
        cached = (account is not None and account.is_active,
                  password_fingerprint(account.password_hash) if account else '')
        _sess_cache.set(check_key, cached, timeout=10)
    if not cached[0] or not session_password_matches(cached[1]):
        try:
            from app.services.account_tracking import end_account_session
            end_account_session('account_invalid')
        except Exception:
            pass
        session.pop('is_admin', None)
        session.pop('admin_name', None)
        session.pop('admin_account_id', None)
        session.pop('pwd_fp', None)


@auth_bp.before_app_request
def load_teacher():
    """每请求轻量校验教师会话：教师被删除/停用时立即清除会话，
    使管理员"停用/删除教师账号"即时生效（对标 load_student_name 的学生侧能力）。

    管理员（is_admin）不设置 teacher_id，不受此校验影响；
    教师账号被停用后重新登录已被 teacher_login 拒绝，此处补上已登录会话的
    即时失效，避免"停用/删除但会话 8 小时内仍可操作"的窗口。

    性能：校验结果缓存 10s，停用/删除后旧会话最多存活 10 秒（可接受）。
    """
    teacher_id = session.get('teacher_id')
    if not teacher_id:
        return
    from app.extensions import cache as _sess_cache
    check_key = f'session:teacher:{teacher_id}'
    cached = _sess_cache.get(check_key)
    if not isinstance(cached, tuple):
        from app.models import Teacher as _T
        teacher = db.session.get(_T, teacher_id)
        cached = (teacher is not None and teacher.is_active,
                  password_fingerprint(teacher.password_hash) if teacher else '')
        _sess_cache.set(check_key, cached, timeout=10)
    if not cached[0] or not session_password_matches(cached[1]):
        _clear_teacher_session('account_invalid')


@auth_bp.before_app_request
def enforce_teacher_readonly():
    """只读教师仅可进入课堂使用资源；所有编辑/隐私接口统一拦截。

    只读模式是账号 + 全校访问码，会话指纹随访问码轮换失效；白名单只保留
    课堂页、资源只读库、AI 对话、心跳与教师上下课。
    """
    if not session.get('is_teacher') or session.get('is_admin'):
        return
    if session.get('teacher_mode') != 'readonly':
        return
    code_hash = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
    session_fp = session.get('readonly_code_fp') or ''
    if (not code_hash or not session_fp or
            not secrets.compare_digest(session_fp,
                                       password_fingerprint(code_hash))):
        _clear_teacher_session()
        if request.path.startswith('/static/') or request.path == '/teacher/login':
            return
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': '只读会话已失效，请重新登录',
                            'code': 403}), 403
        flash('只读访问码已变更，请重新登录', 'warning')
        return redirect(url_for('auth.teacher_login'))

    path = request.path or ''
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        allowed = (
            path in ('/', '/favicon.ico', '/teacher/login', '/teacher/logout',
                     '/teacher/resource-library', '/teacher/schedule',
                     '/teacher/ai_config',
                     '/teacher/dashboard',
                     '/study', '/admin/classroom') or
            path.startswith('/hardware-sim') or
            # 化学仿真工作台（含离线 Ketcher 编辑器帧，课堂大屏 iframe 共用）
            path.startswith('/chem-lab') or
            path.startswith('/sim-lab') or
            path.startswith('/static/') or
            path.startswith('/study/') or
            path.startswith('/api/ai/') or
            path.startswith('/api/heartbeat') or
            path.startswith('/api/events/classroom') or
            path == '/api/healthz'
        )
        if not allowed:
            if path.startswith('/api/'):
                return jsonify({'success': False,
                                'message': '只读模式仅允许课堂使用', 'code': 403}), 403
            flash('只读模式仅允许在课堂中使用资源', 'warning')
            return redirect(url_for('resources.study', mode='classroom'))
        if path == '/study' and request.args.get('mode') != 'classroom':
            return redirect(url_for('resources.study', mode='classroom'))
        return

    allowed_endpoints = {
        'auth.teacher_logout',
        'teaching.start_class',
        'teaching.end_class',
        # 课堂大屏：只读/编辑教师都可查看并设置本人任课班级
        'classroom.save_classroom_settings',
        'classroom.new_classroom_session',
        'classroom.stop_classroom_session',
        'classroom.api_classroom_status',
        'ai.ai_chat',
        'ai.ai_chat_stream',
        'ai.ai_generate_image',
        'ai.ai_clear_session',
        # 只读模式仅允许切换 AI 配置来源（管理员 / 个人），不改密钥
        'ai.teacher_config_api',
    }
    if request.endpoint in allowed_endpoints or path.startswith('/api/heartbeat'):
        return
    if path.startswith('/api/'):
        return jsonify({'success': False,
                        'message': '只读模式禁止修改操作', 'code': 403}), 403
    flash('只读模式不能执行修改操作', 'warning')
    return redirect(url_for('resources.study', mode='classroom'))


def _authenticate_student_by_field(lookup_field, lookup_value, password, active_class_ids, ip_address):
    """
    统一的学生身份验证逻辑
    @param lookup_field: 查询字段名（'student_number' 或 'name'）
    @param lookup_value: 查询字段值
    @param password: 密码
    @param active_class_ids: 当前上课班级ID集合（兼容单个 int/None）
    @param ip_address: 学生IP地址
    @return: (success, message, student)
    """
    if active_class_ids is None:
        id_set = set()
    elif isinstance(active_class_ids, (set, frozenset, list, tuple)):
        id_set = set(active_class_ids)
    else:
        id_set = {active_class_ids}
    # 姓名/学号都可能跨班重复，必须先限定当前上课班级集合，再按密码确定本人。
    query = Student.query.filter_by(**{lookup_field: lookup_value})
    if id_set:
        query = query.filter(Student.class_id.in_(id_set))
    candidates = query.all()
    matched = [item for item in candidates if item.check_password(password)]
    if not matched:
        field_name = '学号' if lookup_field == 'student_number' else '姓名'
        return False, f'{field_name}或密码错误', None
    # 同班同名 + 共享默认密码时，密码会匹配到多个账号，无法确认登录者本人，
    # 此时拒绝登录并引导使用学号，防止任意同名账号被冒名接管。
    if len(matched) > 1:
        return False, '存在同名账号，请使用学号登录', None
    student = matched[0]

    # 检查账户是否被禁用
    if not student.is_activated:
        return False, '该账号已被禁用，请联系管理员', None

    # 检查班级是否命中当前上课班级集合
    if id_set and student.class_id not in id_set:
        return False, '当前不是本班上课时间，请稍后再试', None

    # 更新登录信息（使用本地时间，因为这是业务需求）
    student.ip_address = ip_address
    student.login_time = get_local_now()
    student.last_seen = student.login_time
    db.session.commit()

    # 记录每日签到（upsert 当天记录为 online）
    try:
        from app.services.attendance_service import record_student_login
        record_student_login(student)
    except Exception:
        pass

    return True, '登录成功', student


@auth_bp.route('/', methods=['GET', 'POST'])
def login():
    """学生登录 — 支持学号+密码 或 姓名+密码，受上课班级限制"""
    if request.method == 'GET':
        # 已登录用户访问站点根不应再看到登录表单。
        if session.get('student_id'):
            return redirect(url_for('student_home.student_home'))
        if session.get('is_teacher'):
            return redirect(url_for('teacher_home.teacher_dashboard'))
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard.admin_dashboard'))
    if request.method == 'POST':
        # 清除可能残留的管理员 session
        session.pop('is_admin', None)
        session.pop('is_teacher', None)
        session.pop('teacher_id', None)
        session.pop('teacher_name', None)
        student_number = request.form.get('student_number', '').strip()
        password = request.form.get('password', '').strip()
        name = request.form.get('name', '').strip()
        ip_address = get_client_ip()
        active_class_ids = _get_active_class_ids()

        # 未设置上课班级时禁止所有学生登录
        if not active_class_ids:
            flash('请等待老师设置上课班级', 'warning')
            return render_template('index.html')

        # 方式1: 学号 + 密码登录
        if student_number and password:
            # 三维限流（IP+账号 / 纯账号 / IP 全局）：防单账号爆破、
            # 防换 IP 绕过与横向枚举全班账号
            blocked = student_login_blocked_seconds(ip_address, student_number)
            if blocked:
                flash(f'登录尝试过于频繁，请 {blocked} 秒后再试', 'danger')
                return render_template('index.html')
            success, msg, student = _authenticate_student_by_field(
                'student_number', student_number, password, active_class_ids, ip_address
            )
            if not success:
                if msg == '学号或密码错误':
                    student_login_register_failure(ip_address, student_number)
                flash(msg, 'danger')
                return render_template('index.html')

            student_login_register_success(ip_address, student_number)
            _reset_session_preserving_csrf()
            # 会话绝对过期（PERMANENT_SESSION_LIFETIME）+ 登录时轮换会话 ID，防会话固定
            _rotate_session()
            # 会话绝对过期（PERMANENT_SESSION_LIFETIME）；permanent 须在轮换之后再设置，
            # 因为轮换回退（clear 重建）会清掉 _permanent
            session.permanent = True
            session['student_id'] = student.id
            session['student_name'] = student.name
            session['student_class_id'] = student.class_id
            session['classroom_bound'] = True
            session['pwd_fp'] = password_fingerprint(student.password_hash)
            # 登录后首次页面显示一次欢迎横幅（context processor 读取即消费）
            session['show_welcome'] = True
            # 尚未修改初始密码（共享默认密码）时强制先改密
            if not student.has_changed_password:
                session['must_change_password'] = True
            _start_account_tracking('student', student.id, student.name)
            current_app.logger.info(f"学生登录(学号): {student.name}, IP: {ip_address}")
            return redirect(url_for('student_home.student_home'))

        # 方式2: 姓名 + 密码登录
        if name and password:
            # 三维限流（与学号登录一致）
            blocked = student_login_blocked_seconds(ip_address, name)
            if blocked:
                flash(f'登录尝试过于频繁，请 {blocked} 秒后再试', 'danger')
                return render_template('index.html')
            success, msg, student = _authenticate_student_by_field(
                'name', name, password, active_class_ids, ip_address
            )
            if not success:
                if msg == '姓名或密码错误':
                    student_login_register_failure(ip_address, name)
                flash(msg, 'danger')
                return render_template('index.html')

            student_login_register_success(ip_address, name)
            _reset_session_preserving_csrf()
            # 会话绝对过期 + 登录时轮换会话 ID，防会话固定
            _rotate_session()
            # 会话绝对过期（PERMANENT_SESSION_LIFETIME）；permanent 须在轮换之后再设置，
            # 因为轮换回退（clear 重建）会清掉 _permanent
            session.permanent = True
            session['student_id'] = student.id
            session['student_name'] = student.name
            session['student_class_id'] = student.class_id
            session['classroom_bound'] = True
            session['pwd_fp'] = password_fingerprint(student.password_hash)
            # 登录后首次页面显示一次欢迎横幅（context processor 读取即消费）
            session['show_welcome'] = True
            # 尚未修改初始密码（共享默认密码）时强制先改密
            if not student.has_changed_password:
                session['must_change_password'] = True
            _start_account_tracking('student', student.id, student.name)
            current_app.logger.info(f"学生登录(姓名): {student.name}, IP: {ip_address}")
            return redirect(url_for('student_home.student_home'))

        flash('请填写 学号+密码 或 姓名+密码', 'warning')
        return render_template('index.html')

    return render_template('index.html')


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """管理员登录页"""
    if request.method == 'POST':
        # 清除可能残留的学生 session
        session.pop('student_id', None)
        session.pop('is_teacher', None)
        session.pop('teacher_id', None)
        session.pop('teacher_name', None)
        session.pop('teacher_mode', None)
        session.pop('readonly_code_fp', None)
        ok, result = validate_form(AdminLogin, request.form)
        if not ok:
            flash('; '.join(result))
            return render_template('admin_login.html')
        username = result.username
        password = result.password
        # 登录失败限流：IP 键 + 账号级键（防换 IP 规避；账号级键与 API 版一致）
        throttle_ip = request.remote_addr or ''
        from app.utils import _norm_acct as _norm_admin_acct
        account_key = f'admin:account:{_norm_admin_acct(username)}'
        blocked = (admin_login_blocked_seconds(throttle_ip)
                   or admin_login_blocked_seconds(account_key))
        if blocked:
            flash(f'登录尝试过于频繁，请 {blocked} 秒后再试')
            return render_template('admin_login.html')
        ok, acct_info = verify_admin_account(username, password)
        if ok:
            admin_login_register_success(throttle_ip)
            admin_login_register_success(account_key)
            _reset_session_preserving_csrf()
            # 会话绝对过期 + 登录时轮换会话 ID，防会话固定
            _rotate_session()
            # 会话绝对过期（PERMANENT_SESSION_LIFETIME）；permanent 须在轮换之后再设置，
            # 因为轮换回退（clear 重建）会清掉 _permanent
            session.permanent = True
            session['is_admin'] = True
            # 多账号：记录显示名（表账号）与最近登录
            if acct_info and acct_info[0] == 'table' and acct_info[1]:
                session['admin_name'] = acct_info[1].display_name or acct_info[1].username
                # 自我保护/停用检测用账号主键（显示名≠用户名时按名字反查
                # 会错配，导致管理员可停用/删除自己或误伤他人）
                session['admin_account_id'] = acct_info[1].id
                session['pwd_fp'] = password_fingerprint(acct_info[1].password_hash)
                acct_info[1].last_login_at = datetime.now()
                from app.extensions import db as _db
                _db.session.commit()
            _admin_row = (acct_info[1] if acct_info and acct_info[0] == 'table'
                          else None)
            _start_account_tracking(
                'admin', _admin_row.id if _admin_row else None,
                session.get('admin_name') or username)
            return redirect(url_for('admin_dashboard.admin_dashboard'))
        remaining = admin_login_register_failure(throttle_ip)
        admin_login_register_failure(account_key)
        if remaining:
            flash(f'失败次数过多，已暂时锁定，请 {remaining} 秒后再试')
        else:
            flash('用户名或密码错误')
    return render_template('admin_login.html')


@auth_bp.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    """教师登录页（编辑模式需密码；只读模式需全校只读访问码）"""
    _migrate_teacher_from_file()
    readonly_code_hash = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
    if request.method == 'POST':
        session.pop('student_id', None)
        session.pop('is_admin', None)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        readonly = request.form.get('mode') == 'readonly'
        # 三维限流（与学生登录一致：IP+账号 / 纯账号 / IP 全局）
        blocked = teacher_login_blocked_seconds(get_client_ip(), username)
        if blocked:
            flash(f'登录尝试过于频繁，请 {blocked} 秒后再试', 'danger')
            return render_template('teacher_login.html',
                                   readonly_enabled=bool(readonly_code_hash))
        teacher = Teacher.query.filter_by(username=username).first()
        if readonly:
            access_code = request.form.get('readonly_code', '')
            if not readonly_code_hash:
                flash('管理员尚未配置教师只读访问码', 'danger')
                return render_template('teacher_login.html', readonly_enabled=False)
            if not teacher or not teacher.is_active or not check_password_hash(
                    readonly_code_hash, access_code):
                teacher_login_register_failure(get_client_ip(), username)
                flash('账号或只读访问码错误', 'danger')
                return render_template('teacher_login.html', readonly_enabled=True)
            teacher_login_register_success(get_client_ip(), username)
            _reset_session_preserving_csrf()
            _rotate_session()
            session.permanent = True
            session['is_teacher'] = True
            session['teacher_id'] = teacher.id
            session['teacher_name'] = teacher.display_name or teacher.username
            session['teacher_mode'] = 'readonly'
            session['readonly_code_fp'] = password_fingerprint(readonly_code_hash)
            session['pwd_fp'] = password_fingerprint(teacher.password_hash)
            teacher.last_login_at = get_local_now()
            db.session.commit()
            _start_account_tracking('teacher', teacher.id,
                                    session.get('teacher_name'))
            try:
                from app.extensions import cache as _teacher_cache
                _teacher_cache.delete(f'teacher_ai_transient:{teacher.id}')
            except Exception:
                pass
            return redirect(url_for('resources.study', mode='classroom'))
        if not teacher or not teacher.check_password(password):
            teacher_login_register_failure(get_client_ip(), username)
            flash('用户名或密码错误', 'danger')
            return render_template('teacher_login.html',
                                   readonly_enabled=bool(readonly_code_hash))
        if not teacher.is_active:
            flash('该教师账号已停用', 'danger')
            return render_template('teacher_login.html',
                                   readonly_enabled=bool(readonly_code_hash))
        teacher_login_register_success(get_client_ip(), username)
        _reset_session_preserving_csrf()
        # 会话绝对过期 + 登录时轮换会话 ID，防会话固定。
        # 顺序与其他登录路径统一：先 rotate 再 permanent
        # （轮换回退 clear 会清掉 _permanent，permanent 须在轮换后设置）
        _rotate_session()
        session.permanent = True
        session['is_teacher'] = True
        session['teacher_id'] = teacher.id
        session['teacher_name'] = teacher.display_name or teacher.username
        session['teacher_mode'] = 'edit'
        session.pop('readonly_code_fp', None)
        session['pwd_fp'] = password_fingerprint(teacher.password_hash)
        teacher.last_login_at = get_local_now()
        db.session.commit()
        _start_account_tracking('teacher', teacher.id,
                                session.get('teacher_name'))
        try:
            from app.extensions import cache as _teacher_cache
            _teacher_cache.delete(f'teacher_ai_transient:{teacher.id}')
        except Exception:
            pass
        return redirect(url_for('teacher_home.teacher_dashboard'))
    return render_template('teacher_login.html',
                           readonly_enabled=bool(readonly_code_hash))


@auth_bp.route('/teacher/logout', methods=['POST'])
@teacher_login_required
def teacher_logout():
    """教师退出登录"""
    teacher_id = session.get('teacher_id')
    try:
        from app.services.account_tracking import end_account_session
        end_account_session('logout')
    except Exception:
        pass
    if teacher_id:
        try:
            from app.extensions import cache as _teacher_cache
            _teacher_cache.delete(f'teacher_ai_transient:{teacher_id}')
        except Exception:
            pass
    session.pop('is_teacher', None)
    session.pop('teacher_id', None)
    session.pop('teacher_name', None)
    session.pop('teacher_mode', None)
    session.pop('readonly_code_fp', None)
    session.modified = True
    resp = redirect(url_for('auth.teacher_login'))
    resp.delete_cookie('session', path='/')
    return resp


@auth_bp.route('/admin/teacher_account', methods=['GET', 'POST'])
@admin_login_required
def admin_teacher_account():
    """管理员维护教师账号"""
    _migrate_teacher_from_file()
    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        if action == 'create':
            username = request.form.get('username', '').strip()
            display_name = request.form.get('display_name', '').strip()
            password = request.form.get('password', '')
            grade = request.form.get('grade', '').strip()
            subject_ids = {int(x) for x in request.form.getlist('subject_ids')
                           if str(x).isdigit()}
            class_ids = {int(x) for x in request.form.getlist('class_ids')
                         if str(x).isdigit()}
            selected_subjects = Subject.query.filter(
                Subject.id.in_(subject_ids)).all() if subject_ids else []
            selected_classes = Class.query.filter(
                Class.id.in_(class_ids)).all() if class_ids else []
            if not username or len(password) < 6:
                flash('用户名不能为空，密码至少6位', 'danger')
            elif not selected_subjects:
                flash('请至少选择一个所属学科', 'danger')
            elif not grade or not selected_classes:
                flash('请填写年级并至少选择一个任课班级', 'danger')
            elif Teacher.query.filter_by(username=username).first():
                flash('教师用户名已存在', 'danger')
            else:
                teacher = Teacher(username=username, display_name=display_name or username,
                                  grade=grade)
                teacher.set_password(password)
                teacher.subjects = selected_subjects
                teacher.classes = selected_classes
                db.session.add(teacher)
                db.session.commit()
                flash('教师账号已创建', 'success')
        elif action == 'assign':
            teacher = db.get_or_404(Teacher, request.form.get('teacher_id', type=int))
            grade = request.form.get('grade', '').strip()
            subject_ids = {int(x) for x in request.form.getlist('subject_ids')
                           if str(x).isdigit()}
            class_ids = {int(x) for x in request.form.getlist('class_ids')
                         if str(x).isdigit()}
            selected_subjects = Subject.query.filter(
                Subject.id.in_(subject_ids)).all() if subject_ids else []
            selected_classes = Class.query.filter(
                Class.id.in_(class_ids)).all() if class_ids else []
            if not grade or not selected_subjects or not selected_classes:
                flash('教师至少需要保留一个学科、一个年级和一个班级', 'danger')
            else:
                teacher.grade = grade
                teacher.subjects = selected_subjects
                teacher.classes = selected_classes
                db.session.commit()
                flash('教师学科/年级/班级已更新', 'success')
        elif action == 'subjects':
            teacher = db.get_or_404(Teacher, request.form.get('teacher_id', type=int))
            subject_ids = {int(x) for x in request.form.getlist('subject_ids')
                           if str(x).isdigit()}
            selected_subjects = Subject.query.filter(
                Subject.id.in_(subject_ids)).all() if subject_ids else []
            if not selected_subjects:
                flash('教师至少需要保留一个所属学科', 'danger')
            else:
                teacher.subjects = selected_subjects
                db.session.commit()
                flash('教师所属学科已更新', 'success')
        elif action == 'set_readonly_code':
            code = request.form.get('readonly_code', '')
            if len(code) < 6:
                flash('只读访问码至少6位', 'danger')
            else:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY,
                                 generate_password_hash(code, method='pbkdf2:sha256'))
                db.session.commit()
                flash('教师只读访问码已更新', 'success')
        elif action == 'clear_readonly_code':
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, '')
            db.session.commit()
            flash('教师只读访问码已清除，只读登录已关闭', 'success')
        elif action == 'password':
            teacher = db.get_or_404(Teacher, request.form.get('teacher_id', type=int))
            password = request.form.get('password', '')
            if len(password) < 6:
                flash('新密码至少6位', 'danger')
            else:
                teacher.set_password(password)
                db.session.commit()
                # 重置密码即时让该教师已登录的旧会话失效（指纹比对，见 load_teacher）
                from app.extensions import cache as _t_cache
                _t_cache.delete(f'session:teacher:{teacher.id}')
                flash('教师密码已更新', 'success')
        elif action == 'toggle':
            teacher = db.get_or_404(Teacher, request.form.get('teacher_id', type=int))
            teacher.is_active = not teacher.is_active
            db.session.commit()
            # 停用/启用立即失效教师会话校验缓存（load_teacher 10s TTL）
            try:
                from app.extensions import cache as _t_cache
                _t_cache.delete(f'session:teacher:{teacher.id}')
            except Exception:
                pass
            flash('教师账号状态已更新', 'success')
        elif action == 'delete':
            teacher = db.get_or_404(Teacher, request.form.get('teacher_id', type=int))
            _teacher_id = teacher.id
            _teacher_label = teacher.display_name or teacher.username
            # 解除上课教学记录对该教师的引用（teacher_id FK 无级联，
            # 此前缺陷：有过上课记录的教师删除必 500 且未捕获）
            TeachingSession.query.filter_by(teacher_id=_teacher_id).update(
                {TeachingSession.teacher_id: None}, synchronize_session=False)
            # 作业归属（teacher_id 为普通整数列，置空后由管理员维护）
            from app.models import Homework as _HW
            _HW.query.filter_by(teacher_id=_teacher_id).update(
                {_HW.teacher_id: None}, synchronize_session=False)
            # 教师创建的资源不能因删账号变成 FK 悬空：转交管理员并保留共享
            Resource.query.filter_by(creator_teacher_id=_teacher_id).update(
                {Resource.creator_teacher_id: None,
                 Resource.creator_type: 'admin',
                 Resource.creator_name: f'{_teacher_label}（原教师已删除）'},
                synchronize_session=False)
            # 教师个人 AI 配置为独立表，FK 无级联，先清理再删账号
            from app.models import TeacherAIConfig as _TeacherAIConfig
            from app.models import TeacherAIShare as _TeacherAIShare
            _TeacherAIConfig.query.filter_by(teacher_id=_teacher_id).delete(
                synchronize_session=False)
            _TeacherAIShare.query.filter_by(teacher_id=_teacher_id).delete(
                synchronize_session=False)
            # teacher_subject / resource_share 由 ORM 多对多关系在删除教师时
            # 自动清理；不要先手动 DELETE，否则 flush 会因关联行已不存在
            # 抛出 StaleDataError。
            db.session.delete(teacher)
            db.session.commit()
            # 删除立即失效教师会话校验缓存（load_teacher 10s TTL）
            try:
                from app.extensions import cache as _t_cache
                _t_cache.delete(f'session:teacher:{_teacher_id}')
            except Exception:
                pass
            flash('教师账号已删除', 'success')
        return redirect(url_for('auth.admin_teacher_account'))

    teachers = Teacher.query.order_by(Teacher.created_at.desc()).all()
    subjects = Subject.query.order_by(Subject.sort_order, Subject.name).all()
    classes = Class.query.order_by(Class.name).all()
    existing_grades = {(t.grade or '').strip() for t in teachers if (t.grade or '').strip()}
    grade_options = list(DEFAULT_GRADE_OPTIONS) + sorted(
        existing_grades - set(DEFAULT_GRADE_OPTIONS))
    return render_template('admin_teacher_account.html', teachers=teachers,
                           subjects=subjects, classes=classes, grades=grade_options,
                           grade_options=grade_options,
                           readonly_code_configured=bool(
                               SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''))


@auth_bp.route('/admin/accounts', methods=['GET', 'POST'])
@admin_login_required
def admin_accounts():
    """管理员账号管理（V5.0 多账号）：列表/添加/改密/启停/删除"""
    from app.models import AdminAccount
    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        if action == 'create':
            username = request.form.get('username', '').strip()
            display_name = request.form.get('display_name', '').strip()
            password = request.form.get('password', '')
            if not username or len(password) < 6:
                flash('用户名不能为空，密码至少6位', 'danger')
            elif AdminAccount.query.filter_by(username=username).first():
                flash('管理员用户名已存在', 'danger')
            else:
                account = AdminAccount(username=username,
                                       display_name=display_name or username)
                account.set_password(password)
                db.session.add(account)
                db.session.commit()
                flash(f'管理员账号 {username} 已创建', 'success')
        elif action == 'password':
            account = db.get_or_404(
                AdminAccount,
                request.form.get('account_id', type=int))
            password = request.form.get('password', '')
            if len(password) < 6:
                flash('新密码至少6位', 'danger')
            else:
                account.set_password(password)
                db.session.commit()
                from app.extensions import cache as _aa_cache
                _aa_cache.delete(f'session:admin:{account.id}')
                if account.id == _current_admin_account_id(session):
                    # 改的是自己的密码：同步本会话指纹，其余旧会话失效
                    session['pwd_fp'] = password_fingerprint(account.password_hash)
                flash('管理员密码已更新', 'success')
        elif action == 'toggle':
            account = db.get_or_404(
                AdminAccount,
                request.form.get('account_id', type=int))
            # 不允许停用自己（防把自己锁在门外）
            if account.id == _current_admin_account_id(session):
                flash('不能停用当前登录的账号', 'danger')
            elif account.is_active and AdminAccount.query.filter_by(
                    is_active=True).count() <= 1:
                flash('至少保留一个启用的管理员账号', 'danger')
            else:
                account.is_active = not account.is_active
                db.session.commit()
                # 停用即时失效已登录会话（load_admin 10s TTL 校验）
                from app.extensions import cache as _aa_cache
                _aa_cache.delete(f'session:admin:{account.id}')
                flash('管理员账号状态已更新', 'success')
        elif action == 'delete':
            account = db.get_or_404(
                AdminAccount,
                request.form.get('account_id', type=int))
            if account.id == _current_admin_account_id(session):
                flash('不能删除当前登录的账号', 'danger')
            elif account.is_active and AdminAccount.query.filter_by(
                    is_active=True).count() <= 1:
                # 只在删的是最后一个**启用**账号时拦截（与停用分支同口径）；
                # 此前不看目标状态，已停用的账号在只剩一个启用账号时删不掉
                flash('至少保留一个启用的管理员账号', 'danger')
            else:
                db.session.delete(account)
                db.session.commit()
                # 删除即时失效已登录会话
                from app.extensions import cache as _aa_cache
                _aa_cache.delete(f'session:admin:{account.id}')
                flash('管理员账号已删除', 'success')
        return redirect(url_for('auth.admin_accounts'))

    accounts = AdminAccount.query.order_by(AdminAccount.created_at.desc()).all()
    # 文件账号兼容提示（表账号存在时文件账号仍可登录）
    import os as _os
    from app.utils import get_admin_account_file
    file_account_exists = _os.path.exists(get_admin_account_file())
    return render_template('admin_accounts.html', accounts=accounts,
                           file_account_exists=file_account_exists)


def _current_admin_account_id(session_holder):
    """当前登录的管理员账号 id（表账号）；文件账号/未知返回 None。

    直接用登录时写入的 admin_account_id（此前用 admin_name 反查 username：
    显示名与用户名不一致时保护失效——管理员可停用/删除自己，或显示名
    恰等于他人用户名时误判）。
    """
    return session_holder.get('admin_account_id')


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """学生自主修改密码"""
    student_id = session.get('student_id')
    if not student_id:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()

        # 旧密码猜测限流（与 API 版 pwd-change 一致）：机房共享电脑场景下
        # 防止持有会话的攻击者无限次爆破旧密码后接管账号。
        # 限流键 = student_id + TCP 对端 IP（防 X-Forwarded-For 伪造）。
        from app.utils import admin_login_blocked_seconds, admin_login_register_failure, \
            admin_login_register_success
        throttle_key = f'pwd:{student_id}:{request.remote_addr or ""}'
        blocked = admin_login_blocked_seconds(throttle_key)
        if blocked:
            flash(f'尝试过于频繁，请 {blocked} 秒后再试', 'danger')
            return render_template('change_password.html')

        if not old_pw or not new_pw:
            flash('请填写所有字段', 'danger')
            return render_template('change_password.html')

        if new_pw != confirm_pw:
            flash('两次输入的新密码不一致', 'danger')
            return render_template('change_password.html')

        # 与登录端 password.strip() 保持一致：若保留首尾空格，登录时将永远无法匹配（自锁死）。
        # 上限 50 字符（与 StudentChangePassword schema 的 max_length 一致），
        # 防止超长输入对 pbkdf2 造成不必要的 CPU 开销。
        if len(new_pw) < 6:
            flash('新密码长度至少6位', 'danger')
            return render_template('change_password.html')
        if len(new_pw) > 50:
            flash('新密码长度不能超过50位', 'danger')
            return render_template('change_password.html')

        student = db.session.get(Student, student_id)
        if not student or not student.check_password(old_pw):
            admin_login_register_failure(throttle_key)
            flash('原密码错误', 'danger')
            return render_template('change_password.html')
        admin_login_register_success(throttle_key)

        student.set_password(new_pw)
        student.has_changed_password = True
        db.session.commit()
        # 改密成功后解除强制改密标记，并失效会话校验缓存（load_student_name 10s TTL）；
        # 同步本会话的密码指纹——其余持有旧会话者随之失效
        session.pop('must_change_password', None)
        session['pwd_fp'] = password_fingerprint(student.password_hash)
        try:
            from app.extensions import cache as _pw_cache
            _pw_cache.delete(f'session:check:{student.id}')
        except Exception:
            pass
        flash('密码修改成功', 'success')
        return redirect(url_for('student_home.student_home'))

    return render_template('change_password.html')


@auth_bp.route('/logout', methods=['POST'])
@authenticated_required
def student_logout():
    """学生退出登录"""
    try:
        from app.services.account_tracking import end_account_session
        end_account_session('logout')
    except Exception:
        pass
    session.pop('student_id', None)
    session.pop('is_admin', None)
    session.pop('is_teacher', None)
    session.pop('teacher_id', None)
    session.pop('teacher_name', None)
    session.modified = True
    resp = redirect(url_for('auth.login'))
    resp.delete_cookie('session', path='/')
    return resp


@auth_bp.route('/admin/logout', methods=['POST'])
@admin_login_required
def admin_logout():
    """管理员退出登录"""
    try:
        from app.services.account_tracking import end_account_session
        end_account_session('logout')
    except Exception:
        pass
    session.pop('student_id', None)
    session.pop('is_admin', None)
    session.pop('is_teacher', None)
    session.pop('teacher_id', None)
    session.pop('teacher_name', None)
    session.modified = True
    resp = redirect(url_for('auth.admin_login'))
    resp.delete_cookie('session', path='/')
    return resp
