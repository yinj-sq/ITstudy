"""Flask JSON API 门面；具体路由按领域拆分到 api_*.py。"""
from flask import Blueprint, session

from app.decorators import admin_login_required
from app.extensions import cache
from app.utils import invalidate_exam_list_cache as _invalidate_exam_list_cache  # noqa: F401 (领域模块 re-export，见下)

# 注意：上方别名 re-export 必须位于本文件顶部——api_*.py 领域模块
# `from app.blueprints.api import _invalidate_exam_list_cache`，而本模块
# 末尾反向 import 领域模块注册路由（循环导入），别名先于领域模块加载
# 才能解析。ruff F401"未使用"是误报语义（它是对外 re-export）。


api_bp = Blueprint('api', __name__, url_prefix='/api')


def _parse_bool(value, default=True):
    """把请求里的布尔值安全解析为 bool。

    JSON 可能传真布尔，也可能传字符串 'false'/'0'（后者若直接当真值会把本应
    禁用的账号错误地建成启用）。此处统一按语义解析。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _calc_seat(ip_address, offset):
    """根据IP地址末段和偏移量计算座位号。

    结果 < 1（IP 末段小于偏移量）视为无效返回 None——此前会出现
    "0 号座"/"-7 号座"，考勤页与大屏显示异常。
    """
    if not ip_address:
        return None
    try:
        seat = int(ip_address.split('.')[-1]) - offset
    except (ValueError, IndexError):
        return None
    return seat if seat >= 1 else None


def _is_exam_available_to_student(exam):
    return bool(
        exam and exam.is_active and exam.is_visible and
        getattr(exam, 'is_enabled', True)
    )


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


# ── 通用 SSE 变更推送通道 ────────────────────────────
# 替代高频轮询（课堂大屏/考勤 10s）：
#   写操作处 sse_bump(channel) 递增版本号（缓存键，零 DB 开销）；
#   EventSource 连接每 2s 检查版本，变化即推 'refresh' 事件，前端收到后
#   再 fetch 原数据端点（数据获取逻辑不变，仅把定时轮询换成事件驱动）。
# 连接 300s 上限后正常结束，浏览器 EventSource 自动重连。
# 注意：SSE 必须 GET（EventSource 协议），端点本身只读无副作用。
# 权限：仅管理员可用。学生端考试收卷通知已回退 5s 轮询
# （Waitress 一线程一连接模型下，N 名学生 × 300s 常驻连接会耗尽 48
# 线程池；管理端大屏/考勤各页面 1-2 个连接无此风险）。
# 频道内容不含数据仅含版本号；管理员本就拥有全部数据访问权，
# 无需按频道再做归属校验。

@api_bp.route('/healthz')
def healthz():
    """容器编排/负载均衡健康检查（免鉴权、零敏感信息）。
    仅做轻量连通性探测，不暴露版本/路径等内部细节。"""
    from flask import jsonify
    from sqlalchemy import text as _text
    from app.extensions import db as _db
    db_ok = True
    try:
        _db.session.execute(_text('SELECT 1'))
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return jsonify({'status': 'ok' if db_ok else 'db_unavailable'}), status


@api_bp.route('/events/<path:channel>')
@admin_login_required
def sse_events(channel):
    """SSE 变更推送通道：版本号变化时推送 'refresh' 事件（2s 检查周期）。"""
    import time as _time
    from flask import Response, jsonify
    if not channel or len(channel) > 64:
        return jsonify({'success': False, 'message': '无效通道'}), 400

    def _current_version():
        try:
            return cache.get(f'sse:ver:{channel}')
        except Exception:
            return None

    def generate():
        last_ver = None
        start = _time.time()
        while _time.time() - start < 300:
            ver = _current_version()
            if ver is not None and ver != last_ver:
                last_ver = ver
                yield f'event: refresh\ndata: {ver}\n\n'
            else:
                yield ': keepalive\n\n'
            _time.sleep(2)

    resp = Response(generate(), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    # 注意：不设置 Connection 头——PEP 3333 禁止 WSGI 应用设置 hop-by-hop
    # 头，Waitress 会抛 AssertionError（此前 /api/events/classroom 500）
    return resp


# 学生认证逻辑统一使用 auth 模块中的实现，避免 HTML/API 行为漂移。

# 加载领域路由模块，使其在共享 api_bp 上完成注册。
from app.blueprints import api_auth as _api_auth  # noqa: F401,E402
from app.blueprints import api_exams as _api_exams  # noqa: F401,E402
from app.blueprints import api_questions as _api_questions  # noqa: F401,E402
from app.blueprints import api_resources as _api_resources  # noqa: F401,E402
from app.blueprints import api_trends as _api_trends  # noqa: F401,E402
from app.blueprints import api_results as _api_results  # noqa: F401,E402
from app.blueprints import api_online_students as _api_online_students  # noqa: F401,E402
from app.blueprints import api_logs as _api_logs  # noqa: F401,E402
from app.blueprints import api_classes as _api_classes  # noqa: F401,E402
from app.blueprints import api_student_management as _api_student_management  # noqa: F401,E402
from app.blueprints import api_groups as _api_groups  # noqa: F401,E402
from app.blueprints import api_attendance as _api_attendance  # noqa: F401,E402

__all__ = ["api_bp"]
