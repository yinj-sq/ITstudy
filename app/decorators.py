from functools import wraps
from flask import session, redirect, url_for, jsonify, request


def _wants_json_response():
    return (
        request.path.startswith('/api/')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def login_required(f):
    """学生登录保护装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('student_id'):
            if _wants_json_response():
                return jsonify({'success': False, 'message': '请先登录', 'code': 401}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_login_required(f):
    """管理员登录保护装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            if _wants_json_response():
                return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
            return redirect(url_for('auth.admin_login'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_login_required(f):
    """教师端登录保护：管理员默认拥有教师权限。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_teacher') and not session.get('is_admin'):
            if _wants_json_response():
                return jsonify({'success': False, 'message': '需要教师权限', 'code': 403}), 403
            return redirect(url_for('auth.teacher_login'))
        return f(*args, **kwargs)
    return decorated_function


def teacher_api_required(f):
    """教师端 API 保护：管理员默认拥有教师权限。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_teacher') and not session.get('is_admin'):
            return jsonify({'success': False, 'message': '需要教师权限', 'code': 403}), 403
        return f(*args, **kwargs)
    return decorated_function


def teacher_edit_required(f):
    """教师编辑权限：管理员或编辑模式教师；只读模式只能查看课堂。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_admin'):
            return f(*args, **kwargs)
        if not session.get('is_teacher'):
            if _wants_json_response():
                return jsonify({'success': False, 'message': '需要教师权限',
                                'code': 403}), 403
            return redirect(url_for('auth.teacher_login'))
        if session.get('teacher_mode') == 'readonly':
            if _wants_json_response():
                return jsonify({'success': False,
                                'message': '只读模式不能执行编辑操作',
                                'code': 403}), 403
            return redirect(url_for('resources.study', mode='classroom'))
        return f(*args, **kwargs)
    return decorated_function


def authenticated_required(f):
    """任一已登录身份保护：学生、教师或管理员。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not (session.get('student_id') or session.get('is_teacher') or session.get('is_admin')):
            if _wants_json_response():
                return jsonify({'success': False, 'message': '请先登录', 'code': 401}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def api_login_required(f):
    """API 端点登录保护 — 学生或管理员均可访问，返回 JSON 错误"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('student_id') and not session.get('is_admin') and not session.get('is_teacher'):
            return jsonify({'success': False, 'message': '请先登录', 'code': 401}), 401
        # 强制首登改密（SPA 侧补齐）：未改初始密码的学生仅放行认证类端点
        # （登录/改密/登出/状态/心跳），其余业务 API 一律 403——
        # 此前 SPA 登录无视 must_change_password 标志，可绕过强制改密使用全部功能
        if session.get('must_change_password') and \
                not session.get('is_admin') and not session.get('is_teacher'):
            from flask import request as _req
            path = _req.path or ''
            if not path.startswith('/api/auth/') and not path.startswith('/api/heartbeat'):
                return jsonify({
                    'success': False, 'message': '请先修改初始密码', 'code': 403}), 403
        return f(*args, **kwargs)
    return decorated_function


def api_admin_required(f):
    """API 端点管理员保护 — 仅管理员可访问，返回 JSON 错误"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        return f(*args, **kwargs)
    return decorated_function


def is_admin():
    """检查当前用户是否是管理员"""
    return session.get('is_admin', False)


def is_teacher():
    """检查当前用户是否是教师或管理员。"""
    return bool(session.get('is_teacher') or session.get('is_admin'))
