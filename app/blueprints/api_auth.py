"""由 API 门面模块加载的领域路由。"""
from datetime import datetime

from flask import current_app, jsonify, request, session

from app.extensions import cache, db
from app.models import (
    Student,
)
from app.decorators import login_required
from app.utils import (
    admin_login_blocked_seconds, admin_login_register_failure,
    admin_login_register_success, get_client_ip,
    student_login_blocked_seconds, student_login_register_failure,
    student_login_register_success,
    verify_admin_account,
)
from app.blueprints.auth import (_authenticate_student_by_field, _get_active_class_ids,
                                 _rotate_session)
from app.blueprints.api import (
    api_bp, _reset_session_preserving_csrf,
)

# ──────────────────────────────────────────────
#  Auth
# ──────────────────────────────────────────────


@api_bp.route('/auth/status', methods=['GET'])
def auth_status():
    """返回当前会话状态"""
    student_id = session.get('student_id')
    name = ''
    if student_id:
        student = db.session.get(Student, student_id)
        if student:
            name = student.name
    return jsonify({
        'success': True,
        'data': {
            'student_id': student_id,
            'is_admin': session.get('is_admin', False),
            'is_teacher': session.get('is_teacher', False),
            'teacher_name': session.get('teacher_name', ''),
            'name': name
        },
        'message': 'ok'
    })


@api_bp.route('/auth/login', methods=['POST'])
def auth_login():
    """学生登录（支持学号+密码 或 姓名+密码，受上课班级限制）"""
    data = request.get_json(force=True, silent=True) or request.form
    # JSON 可能为数组/字符串等非对象（.get 会 AttributeError → 500）
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': '登录字段格式无效'}), 400
    if not all(isinstance(data.get(key, ''), str) for key in ('student_number', 'password', 'name')):
        return jsonify({'success': False, 'message': '登录字段格式无效'}), 400
    student_number = data.get('student_number', '').strip()
    password = data.get('password', '').strip()
    name = data.get('name', '').strip()
    ip_address = get_client_ip()
    active_class_ids = _get_active_class_ids()

    # 未设置上课班级时禁止所有学生登录
    if not active_class_ids:
        return jsonify({'success': False, 'message': '请等待老师设置上课班级'}), 403

    # 学号 + 密码登录
    if student_number and password:
        # 三维限流（IP+账号 / 纯账号 / IP 全局）：
        # 纯账号维度防换 IP/换学号绕过单账号爆破；IP 全局维度防
        # 「对全班账号依次试常见弱口令」横向枚举
        blocked = student_login_blocked_seconds(ip_address, student_number)
        if blocked:
            return jsonify({'success': False, 'message': f'登录尝试过于频繁，请 {blocked} 秒后再试',
                            'retry_after': blocked}), 429
        success, message, student = _authenticate_student_by_field(
            'student_number', student_number, password, active_class_ids, ip_address
        )
        if not success:
            if message == '学号或密码错误':
                student_login_register_failure(ip_address, student_number)
            status = 403 if message != '学号或密码错误' else 401
            return jsonify({'success': False, 'message': message}), status
        student_login_register_success(ip_address, student_number)
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
        from app.utils import password_fingerprint
        session['pwd_fp'] = password_fingerprint(student.password_hash)
        # 尚未修改初始密码（共享默认密码）时强制先改密（load_student_name 统一拦截）
        if not student.has_changed_password:
            session['must_change_password'] = True
        try:
            from app.services.account_tracking import start_account_session
            start_account_session('student', student.id, student.name,
                                  channel='api')
        except Exception:
            pass
        return jsonify({
            'success': True,
            'data': {'student_id': student.id, 'name': student.name, 'class': student.student_class,
                     # SPA 前端据此跳转改密页（HTML 端由 load_student_name 统一拦截）
                     'must_change_password': bool(session.get('must_change_password'))},
            'message': '登录成功'
        })

    # 姓名 + 密码登录
    if name and password:
        # 三维限流（与学号路径一致）
        blocked = student_login_blocked_seconds(ip_address, name)
        if blocked:
            return jsonify({'success': False, 'message': f'登录尝试过于频繁，请 {blocked} 秒后再试',
                            'retry_after': blocked}), 429
        success, message, student = _authenticate_student_by_field(
            'name', name, password, active_class_ids, ip_address
        )
        if not success:
            if message == '姓名或密码错误':
                student_login_register_failure(ip_address, name)
            status = 403 if message != '姓名或密码错误' else 401
            return jsonify({'success': False, 'message': message}), status
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
        from app.utils import password_fingerprint
        session['pwd_fp'] = password_fingerprint(student.password_hash)
        # 尚未修改初始密码（共享默认密码）时强制先改密（load_student_name 统一拦截）
        if not student.has_changed_password:
            session['must_change_password'] = True
        try:
            from app.services.account_tracking import start_account_session
            start_account_session('student', student.id, student.name,
                                  channel='api')
        except Exception:
            pass
        return jsonify({
            'success': True,
            'data': {'student_id': student.id, 'name': student.name, 'class': student.student_class,
                     # SPA 前端据此跳转改密页（HTML 端由 load_student_name 统一拦截）
                     'must_change_password': bool(session.get('must_change_password'))},
            'message': '登录成功'
        })

    return jsonify({'success': False, 'message': '请提供学号+密码或姓名+密码'}), 400


@api_bp.route('/heartbeat', methods=['POST'])
@login_required
def heartbeat():
    """学生在线心跳：刷新 last_seen，供考勤和在线列表使用。

    频率限制：15s 内重复心跳直接返回缓存值（不查库不写库）。此前接口
    本身无请求级限流，脚本可高频调用维持虚假在线（30s 写库节流不挡请求）。
    心跳的真实周期为 60s，15s 缓存完全覆盖正常节奏。
    """
    from datetime import timedelta
    student_id = session.get('student_id')
    # 短 TTL 心跳缓存：命中即视为"刚心跳过"，直接返回成功
    from app.extensions import cache as _hb_cache
    _hb_key = f'hb:{student_id}'
    cached_ts = _hb_cache.get(_hb_key)
    if cached_ts:
        return jsonify({'success': True, 'last_seen': cached_ts})
    student = db.session.get(Student, student_id)
    if not student:
        return jsonify({'success': False, 'message': '学生不存在'}), 404
    # 仅当学生从"离线"变为"在线"时才失效在线列表缓存，
    # 避免每个学生每 60 秒一次心跳都触发 cache.delete（250 人 ≈ 4 次/秒
    # 的缓存删除风暴，使在线列表缓存形同虚设）。
    now = datetime.now()
    was_offline = not student.last_seen or \
        student.last_seen < now - timedelta(minutes=30)
    # 写库节流：last_seen 距今 <30s 时跳过 commit（心跳 60s 一次，精度需求低，
    # 避免 250 人 × 60s 的持续 PG 写入与 WAL 增长）；离线→在线边界必须立即写。
    if not was_offline and student.last_seen and \
            now - student.last_seen < timedelta(seconds=30):
        return jsonify({'success': True, 'last_seen': student.last_seen.strftime('%Y-%m-%d %H:%M:%S')})
    student.last_seen = now
    if not student.login_time:
        student.login_time = student.last_seen
    ip_address = get_client_ip()
    if ip_address:
        student.ip_address = ip_address
    db.session.commit()
    if was_offline:
        cache.delete('api:students:online')
        # SSE 推送：学生由离线转在线，课堂大屏/考勤页立即感知
        # （在线上线频率低，不节流；普通心跳不推送，避免 250 人 × 60s 风暴）
        from app.utils import sse_bump as _hb_bump
        _hb_bump('classroom')
    # 更新当日签到记录的最后活跃时间
    try:
        from app.services.attendance_service import update_student_last_seen
        update_student_last_seen(student)
    except Exception:
        pass
    # 写入心跳缓存（15s TTL）挡住重复调用
    _hb_cache.set(_hb_key, student.last_seen.strftime('%Y-%m-%d %H:%M:%S'), timeout=15)
    return jsonify({'success': True, 'last_seen': student.last_seen.strftime('%Y-%m-%d %H:%M:%S')})


@api_bp.route('/auth/admin-login', methods=['POST'])
def auth_admin_login():
    """管理员登录 — 返回 JSON"""
    data = request.get_json(force=True, silent=True) or request.form
    if not isinstance(data, dict):
        return jsonify({'success': False, 'message': '登录字段格式无效'}), 400
    if not isinstance(data.get('username', ''), str) or not isinstance(data.get('password', ''), str):
        return jsonify({'success': False, 'message': '登录字段格式无效'}), 400
    username = data.get('username', '').strip()
    # 密码不 strip：与 HTML 登录/建号口径一致（首尾带空格的口令在 SPA 端才登得上）
    password = data.get('password', '')
    # 长度上限：用户名会进入限流缓存 key（未截断时匿名者可写入 25MB 级
    # key 撑爆进程内缓存）；密码上限与建号/改密口径一致
    if len(username) > 80 or len(password) > 128:
        return jsonify({'success': False, 'message': '用户名或密码格式无效'}), 400
    throttle_ip = request.remote_addr or ''
    # 账号级限流（与学生/教师路径一致）：仅 IP 键可被换 IP 规避
    # （IPv6 前缀池/代理池）→ 远程登录开启后对管理员口令无限爆破
    from app.utils import _norm_acct
    account_key = f'admin:account:{_norm_acct(username)}'
    blocked = (admin_login_blocked_seconds(throttle_ip)
               or admin_login_blocked_seconds(account_key))
    if blocked:
        return jsonify({'success': False, 'message': f'登录尝试过于频繁，请 {blocked} 秒后再试',
                        'retry_after': blocked}), 429
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
        # 多账号：记录显示名（表账号）与最近登录；admin_account_id 供
        # 自我保护/停用检测（显示名≠用户名时按名字反查会错配）
        if acct_info and acct_info[0] == 'table' and acct_info[1]:
            session['admin_name'] = acct_info[1].display_name or acct_info[1].username
            session['admin_account_id'] = acct_info[1].id
            from app.utils import password_fingerprint
            session['pwd_fp'] = password_fingerprint(acct_info[1].password_hash)
            from datetime import datetime as _dt
            acct_info[1].last_login_at = _dt.now()
            from app.extensions import db as _db
            _db.session.commit()
        try:
            from app.services.account_tracking import start_account_session
            _admin_row = (acct_info[1]
                          if acct_info and acct_info[0] == 'table' else None)
            start_account_session(
                'admin', _admin_row.id if _admin_row else None,
                session.get('admin_name') or username, channel='api')
        except Exception:
            pass
        return jsonify({
            'success': True,
            'data': {'is_admin': True},
            'message': '管理员登录成功'
        })
    remaining = admin_login_register_failure(throttle_ip)
    admin_login_register_failure(account_key)
    current_app.logger.warning("API 管理员登录失败: username=%r", username)
    if remaining:
        return jsonify({'success': False, 'message': f'失败次数过多，已暂时锁定，请 {remaining} 秒后再试',
                        'retry_after': remaining}), 429
    return jsonify({'success': False, 'message': '用户名或密码错误'}), 401


@api_bp.route('/auth/logout', methods=['POST'])
def auth_logout():
    """退出登录"""
    try:
        from app.services.account_tracking import end_account_session
        end_account_session('logout')
    except Exception:
        pass
    session.clear()
    return jsonify({'success': True, 'message': '已退出登录'})
