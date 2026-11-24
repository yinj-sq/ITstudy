"""ITstudy 应用工厂 — 版权所有 (C) 2025-2026 YINJUN"""
import os

from flask import Flask
from app.config import Config
from app.extensions import db, cache, migrate
from app.filters import register_filters
from app.utils import (versioned_static, add_cache_headers, parse_int,
                       PRIVATE_UPLOAD_PREFIXES, has_dot_segment,
                       has_win_path_alias, install_precompressed_static)
from app.models import Exam


def create_app():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__,
                template_folder=os.path.join(base_dir, 'templates'),
                static_folder=os.path.join(base_dir, 'static'))

    # 只有显式声明位于可信反向代理之后，才接受 X-Forwarded-*。
    if Config.TRUST_PROXY_HEADERS:
        from werkzeug.middleware.proxy_fix import ProxyFix
        _proxy_secret = getattr(Config, 'PROXY_SECRET', '')
        _inner_fix = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0)
        if _proxy_secret:
            # 代理密钥门（可选加固）：仅当请求携带 X-Proxy-Secret 且值匹配
            # 时才应用 ProxyFix（采信 XFF）；其余请求（绕过代理直连应用端口）
            # 保持原始 TCP 对端地址、不采信任何转发头。
            # 威胁场景：TRUST_PROXY_HEADERS=1 且应用端口对内网可达时，任何
            # 主机可直连 :5000 携带伪造 XFF——ProxyFix 会把 remote_addr 改写
            # 为伪造值，绕过"管理员远程登录已关闭"开关（is_local 判本机）、
            # 逐请求换新登录限流 IP 维度、伪造座位号/考勤/审计 IP。
            # 部署要求：反代需配置转发该头（docs/itstudy.conf 样例已含）。
            import secrets as _secrets

            class _TrustedProxyGate:
                def __init__(self, app, fix):
                    self.app = app
                    self.fix = fix

                def __call__(self, environ, start_response):
                    supplied = environ.get('HTTP_X_PROXY_SECRET', '')
                    trusted = bool(supplied) and _secrets.compare_digest(
                        supplied.encode('utf-8'), _proxy_secret.encode('utf-8'))
                    environ['itstudy.trusted_proxy'] = trusted
                    if trusted:
                        return self.fix(environ, start_response)
                    return self.app(environ, start_response)

            app.wsgi_app = _TrustedProxyGate(app.wsgi_app, _inner_fix)
        else:
            # 未配置密钥：保持旧行为（信任所有请求的 XFF），并在请求环境
            # 标记为可信——与"信任所有来源转发头"的旧语义一致
            class _MarkTrusted:
                def __init__(self, app, fix):
                    self.app = app
                    self.fix = fix

                def __call__(self, environ, start_response):
                    environ['itstudy.trusted_proxy'] = True
                    return self.fix(environ, start_response)

            app.wsgi_app = _MarkTrusted(app.wsgi_app, _inner_fix)
    app.config.from_object(Config)

    if app.config.get('TRUST_PROXY_HEADERS') and not app.config.get('PROXY_SECRET'):
        app.logger.warning(
            '安全告警：TRUST_PROXY_HEADERS=1 但未设置 PROXY_SECRET。应用会采信'
            '任意来源的 X-Forwarded-For，内网直连应用端口的主机可伪造本机地址/'
            '限流键。请设置 PROXY_SECRET 并让反向代理注入 X-Proxy-Secret。')

    # 自动创建必要目录（使用绝对路径）
    os.makedirs(os.path.join(base_dir, 'data'), exist_ok=True)
    os.makedirs(os.path.join(base_dir, 'static', 'uploads'), exist_ok=True)
    os.makedirs(os.path.join(base_dir, 'static', 'question_img'), exist_ok=True)
    cache_dir = app.config.get('CACHE_DIR', os.path.join('data', 'cache'))
    os.makedirs(cache_dir, exist_ok=True)

    # 日志目录（使用绝对路径，避免以 Windows 服务运行时 CWD 不确定导致日志写到别处）
    log_dir = os.path.join(base_dir, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # 日志配置
    import logging
    from logging.handlers import RotatingFileHandler
    # 设置 Waitress 日志级别为 WARNING，避免记录客户端断开连接等 INFO 级别信息
    waitress_logger = logging.getLogger('waitress')
    waitress_logger.setLevel(logging.WARNING)

    # 先重置根 logger 已有的 handlers，避免 basicConfig 重复添加
    root_logger = logging.getLogger()
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    # 滚动日志：单文件最大 10MB，保留 10 个备份（app.log.1 ~ app.log.10）
    rotating_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding='utf-8'
    )
    rotating_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(rotating_handler)
    root_logger.addHandler(stream_handler)

    # 初始化扩展
    db.init_app(app)
    cache.init_app(app)
    migrate.init_app(app, db)

    # gzip/brotli 压缩：静态与 API 响应传输体积降 70-80%
    # （Waitress 无内建压缩；flask-compress 按 Accept-Encoding 协商）
    # COMPRESS_STREAMS=True：Flask 的 send_file/send_from_directory 响应
    # 是流式（streamed），默认不压缩（9.7MB 的 jit-viewer 等大文件白白传输）；
    # 开启后文本类静态资源也会被压缩（视频/图片等不在压缩 MIME 集合内，不受影响）。
    # 流式算法默认不含 gzip（保守配置），_compress_chunks 实际完整支持 gzip，
    # 显式加入保证纯 gzip 客户端（部分老旧浏览器）也能获得压缩。
    app.config['COMPRESS_STREAMS'] = True
    app.config['COMPRESS_ALGORITHM_STREAMING'] = ['zstd', 'br', 'gzip', 'deflate']
    from flask_compress import Compress
    Compress(app)

    # 注册 SQLAlchemy 慢查询监控（>500ms 警告）
    _register_slow_query_logger(app)

    # 自动创建 PostgreSQL 数据库（如不存在）
    try:
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        conn = psycopg2.connect(
            host=app.config['DB_HOST'], port=app.config['DB_PORT'],
            user=app.config['DB_USER'], password=app.config['DB_PASS'],
            dbname='postgres'
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(
            'SELECT 1 FROM pg_database WHERE datname = %s',
            (app.config['DB_NAME'],)
        )
        if not cur.fetchone():
            cur.execute(
                sql.SQL('CREATE DATABASE {}').format(
                    sql.Identifier(str(app.config['DB_NAME']))
                )
            )
        cur.close()
        conn.close()
    except Exception as e:
        # 数据库可能已存在，或 PostgreSQL 服务不可用；不阻塞启动
        app.logger.warning('自动创建数据库失败 (可能已存在或服务不可用): %s', str(e))

    # 静态文件预压缩直出（无 Nginx 时也有 gzip_static 的效果）
    install_precompressed_static(app)

    # 学习页资源数据结构升级（文件网格改为展开时按需）：清理旧缓存，
    # 避免升级后沿用缺少 is_file_resource/file_count 字段的旧数据。
    try:
        import time as _time
        with app.app_context():
            cache.delete('study:resources:student')
            cache.delete('study:resources:classroom')
            cache.set('study:resources:scope:version', _time.time_ns(),
                      timeout=86400)
    except Exception:
        pass

    # 模板自动重载：仅 DEBUG 模式启用，生产关闭以减少磁盘 stat
    auto_reload = bool(app.config.get('DEBUG'))
    app.jinja_env.auto_reload = auto_reload
    app.config['TEMPLATES_AUTO_RELOAD'] = auto_reload

    # 注册 Jinja2 过滤器
    register_filters(app)

    # 注册静态资源版本控制
    app.jinja_env.globals['versioned_static'] = lambda f: versioned_static(f)

    # 注册 context processor
    _RECENT_EXAMS_CACHE_KEY = 'lookup:recent_exams'

    @app.context_processor
    def inject_exam():
        # 最近试卷列表缓存（TTL 30s）：base.html 导航下拉每页渲染都会
        # 查询，加缓存避免所有后台页面共享一次全表查询。
        # 存纯 dict 列表而非 ORM 实例：filesystem 缓存 pickle 模型实例后
        # 反序列化为 detached 状态，访问懒加载关系会抛 DetachedInstanceError。
        recent = cache.get(_RECENT_EXAMS_CACHE_KEY)
        if recent is None:
            recent = [{'id': e.id, 'name': e.name}
                      for e in Exam.query.order_by(Exam.id.desc()).limit(20).all()]
            cache.set(_RECENT_EXAMS_CACHE_KEY, recent, timeout=30)
        return {'Exam': Exam, 'recent_exams': recent}

    @app.before_request
    def _mark_request_start():
        from flask import g
        import time as _time
        g._itstudy_req_start = _time.perf_counter()

    @app.before_request
    def _touch_account_session():
        try:
            from app.services.account_tracking import touch_account_session
            touch_account_session()
        except Exception:
            pass

    @app.after_request
    def _record_account_page_view(response):
        try:
            if response.status_code == 200 and 'text/html' in (
                    response.headers.get('Content-Type') or '').lower():
                from app.services.account_tracking import record_page_view
                record_page_view()
        except Exception:
            pass
        return response

    @app.after_request
    def _log_slow_page_requests(response):
        """动态页面超过 800ms 记一条慢请求日志，便于定位菜单切换卡顿。"""
        from flask import g, request
        import time as _time
        start = getattr(g, '_itstudy_req_start', None)
        if start is None or request.path.startswith(('/static/', '/api/')):
            return response
        elapsed_ms = (_time.perf_counter() - start) * 1000
        if elapsed_ms >= 800:
            app.logger.warning('慢页面请求 %s %s %.0fms -> %s',
                               request.method, request.path, elapsed_ms,
                               response.status_code)
        return response

    # 注册缓存头中间件
    app.after_request(add_cache_headers)

    # 反代部署未开 TRUST_PROXY_HEADERS 的检测（一次性警告）：
    # 未开启时所有客户端共享 nginx 内网 IP 作为限流键/审计 IP——
    # 任一账号触发封禁会连带全站登录锁定。检测到转发头即提示部署方。
    _proxy_header_warned = [False]

    @app.before_request
    def _warn_untrusted_proxy_headers():
        from flask import request as _req
        if _proxy_header_warned[0]:
            return None
        if not app.config.get('TRUST_PROXY_HEADERS') and (
                _req.headers.get('X-Forwarded-For') or _req.headers.get('X-Real-IP')):
            _proxy_header_warned[0] = True
            app.logger.warning(
                '检测到 X-Forwarded-For/X-Real-IP 转发头但未设置 '
                'TRUST_PROXY_HEADERS=1：若部署在 nginx 等反向代理之后，'
                '所有客户端将共享代理内网 IP（IP 限流键/审计 IP 失效），'
                '请设置环境变量 TRUST_PROXY_HEADERS=1 并确保代理头仅由'
                '可信代理写入')

    # 上传体积限制：按请求类型区分——
    #   JSON 请求（get_json 全量读入内存）：严格 25MB，防内存型 DoS
    #   multipart 上传：管理员不限，非管理员 200MB（各端点自身的单文件
    #   上限如作业 50/100MB、网盘 200MB、活动 20MB 在解析层之上生效）
    @app.before_request
    def _enforce_upload_size_by_role():
        from flask import request, session, jsonify
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return None
        content_length = request.content_length
        content_type = (request.content_type or '').lower()
        is_json = content_type.startswith('application/json')
        is_multipart = content_type.startswith('multipart/')
        # 端点是否可能解析 JSON：登录等 API 用 get_json(force=True) 不看
        # Content-Type，把 text/plain 当 JSON 解析——只按头判定会留下
        # 200MB 强制 JSON 解析的内存 DoS 面。非 multipart 的 API 请求
        # 一律按 JSON 体积处理。
        parses_json = is_json or (request.path.startswith('/api/') and not is_multipart)
        if content_length is not None:
            pass  # 有 Content-Length（含显式 0）：走下方统一按角色校验
        elif parses_json:
            # chunked 传输编码请求无 Content-Length——直接跳过会把 JSON
            # 内存型 DoS 防线从 25MB 退化到全局 MAX_CONTENT_LENGTH=210MB
            # （Werkzeug 仅在 wsgi.input_terminated 时兜底），故 fail-closed
            # 拒绝无长度声明的 JSON 请求（正常客户端/反代均带 Content-Length）
            return jsonify({
                'success': False,
                'message': 'JSON 请求缺少 Content-Length，请使用标准方式提交'
            }), 411
        else:
            return None
        if parses_json:
            # JSON 内存型 DoS 防护；25MB 覆盖三处 PPTist 课件缓存保存端点
            # （课堂课件/个人网盘/小组网盘均自限 20MB，含 base64 图片的
            # slides JSON 体积较大）
            limit = 25 * 1024 * 1024
        elif session.get('is_admin'):
            return None
        else:
            limit = app.config.get('NON_ADMIN_UPLOAD_LIMIT', 200 * 1024 * 1024)
        if content_length > limit:
            mb = limit // (1024 * 1024)
            if request.path.startswith('/api/') or \
                    request.accept_mimetypes.best == 'application/json':
                return jsonify({
                    'success': False,
                    'message': f'上传内容超过 {mb}MB 限制'
                }), 413
            return f'上传内容超过 {mb}MB 限制', 413
        return None

    @app.before_request
    def _enforce_system_switches():
        from flask import request, session, jsonify
        path = request.path or '/'
        if path.startswith('/static/') or request.endpoint == 'resources.courseware_view':
            # 无 Cookie 的课件读取凭证由路由按签发身份校验维护开关。
            return None

        def wants_json():
            return (
                path.startswith('/api/')
                or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or request.accept_mimetypes.best == 'application/json'
            )

        def is_local():
            remote = request.remote_addr or ''
            if remote in ('127.0.0.1', '::1', 'localhost'):
                # fail-closed：本机反代（nginx 与应用同机）且未启用
                # TRUST_PROXY_HEADERS 时 remote_addr 恒为 127.0.0.1，
                # 所有外部客户端都会被误判为"本机"，"管理员远程登录已关闭"
                # 设置被整体旁路（fail-open）。请求携带 X-Forwarded-For
                # 说明确有代理注入，此时按非本机来源处理。
                # 代价与出口：正确部署本就要求反代后设置 TRUST_PROXY_HEADERS=1
                # （docs/itstudy.conf 头部说明）；确需经未配置的反代登录管理端，
                # 可在系统设置开启"允许管理员远程登录"，或直连应用端口。
                if (not app.config.get('TRUST_PROXY_HEADERS')
                        and request.headers.get('X-Forwarded-For')):
                    return False
                return True
            return False

        # 学生端路径前缀：系统开关异常时对这些路径 fail-closed（阻断），
        # 避免数据库故障导致维护模式等访问控制被绕过。
        _STUDENT_PATH_PREFIXES = (
            '/study', '/student', '/exam', '/groups', '/change-password',
            '/online_exam', '/submit_exam', '/result', '/pptist',
            '/download_python_file', '/upload_python_answer',
            # 作品/活动文档读取面（学生可读）：此前不在清单也不以 /api/ 开头，
            # 维护模式（student_access_enabled=false）下 fail-open——
            # 学生仍能直取他人作品/活动文档
            '/works', '/activity',
            '/api/heartbeat', '/api/auth/login'
        )
        _is_student_path = path == '/' or any(
            path.startswith(prefix) for prefix in _STUDENT_PATH_PREFIXES
        )

        try:
            from app.models import SystemConfig

            if not SystemConfig.get_bool('admin_remote_enabled', False):
                if path in ('/admin/login', '/api/auth/admin-login') and not is_local():
                    if wants_json():
                        return jsonify({'success': False, 'message': '管理员远程登录已关闭'}), 403
                    return '<h1>403</h1><p>管理员远程登录已关闭。</p>', 403

            if SystemConfig.get_bool('student_access_enabled', True):
                return None
            if session.get('is_admin') or session.get('is_teacher'):
                return None
            # 学生端维护模式：fail-closed。仅放行登录/认证/静态资源与
            # 明确的学生入口路径；其余所有学生数据路径（页面 + /api/*）一律
            # 503。此前仅按白名单前缀拦截，/api/exams、/api/resources、
            # /api/ai/* 等已登录学生端点可绕过开关继续使用。
            if path.startswith('/static/') or path == '/':
                return None
            # 探活端点豁免维护开关：docker compose up --wait / LB 依据
            # healthz 判定容器存活，学生端关闭 ≠ 容器故障（误判会导致
            # 编排重启循环或后端被摘除）
            if path == '/api/healthz':
                return None
            if path.startswith('/api/auth/') or path == '/change-password':
                return None
            if _is_student_path or path.startswith('/api/'):
                if wants_json():
                    return jsonify({'success': False, 'message': '学生端维护中'}), 503
                return '<h1>系统维护中</h1><p>学生端暂时关闭，请稍后再试。</p>', 503
        except Exception:
            app.logger.debug('系统开关检查失败', exc_info=True)
            # 远程管理员登录开关读不到时按其默认值（关闭）处理：否则 DB 抖动
            # 期间非本机可直达管理员登录，并回落到文件账号完成登录
            if path in ('/admin/login', '/api/auth/admin-login') and not is_local():
                if wants_json():
                    return jsonify({'success': False, 'message': '系统暂时不可用'}), 503
                return '<h1>系统暂时不可用</h1><p>请稍后再试。</p>', 503
            # 对学生端路径 fail-closed：开关状态无法确认时，保守阻断学生端访问。
            # 管理员/教师路径放行，确保管理后台在 DB 故障时仍可介入。
            if not session.get('is_admin') and not session.get('is_teacher') and _is_student_path:
                if wants_json():
                    return jsonify({'success': False, 'message': '系统暂时不可用'}), 503
                return '<h1>系统暂时不可用</h1><p>请稍后再试。</p>', 503
        return None

    # ── Host 头伪造防护 ──
    # 配置 trusted_hosts（逗号分隔）时强制校验 Host 头，防止伪造 Host
    # 污染日志、生成链接或配合缓存投毒；未配置时保持宽松（默认行为）。
    # 白名单放在 HOST_ALLOWLIST 而非 Flask 原生的 TRUSTED_HOSTS，原因见 config.py。
    _HOST_ALLOWLIST = app.config.get('HOST_ALLOWLIST')
    if _HOST_ALLOWLIST:
        _host_allowlist = {h.strip('[]').lower() for h in _HOST_ALLOWLIST}

        @app.before_request
        def _enforce_trusted_host():
            from flask import request, jsonify
            # 容器内 HEALTHCHECK / 本机探活走 127.0.0.1，不在对外白名单内；
            # 该端点免鉴权且零敏感信息，按 Host 拦截会让设置了 TRUSTED_HOSTS
            # 的部署永久 unhealthy（compose --wait 卡死、LB 摘除后端）
            if request.path == '/api/healthz':
                return None
            # 剥离端口：IPv6 字面量形如 [::1] 或 [::1]:5000，不能按末个冒号切
            raw_host = (request.host or '').lower()
            if raw_host.startswith('['):
                host = raw_host[1:raw_host.find(']')] if ']' in raw_host else raw_host
            else:
                host = raw_host.partition(':')[0]
            if host not in _host_allowlist:
                wants_json = (
                    request.path.startswith('/api/')
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    or request.accept_mimetypes.best == 'application/json'
                )
                if wants_json:
                    return jsonify({'success': False, 'message': '无效的 Host 头'}), 400
                return '<h1>400</h1><p>无效的 Host 头。</p>', 400

    # ── CSRF 保护（SPA 前端通过 axios 自动发送 X-CSRFToken）──
    @app.before_request
    def _csrf_protect():
        from flask import request, session, jsonify
        import secrets

        # 确保 session 中始终有 csrf_token，并设置同名 cookie 供 JS 读取
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)

        # 对所有写请求校验 CSRF token，兼容表单字段和 AJAX 头
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            expected = session.get('csrf_token', '')
            token = (
                request.headers.get('X-CSRFToken')
                or request.headers.get('X-CSRF-Token')
                or request.form.get('csrf_token')
                or request.form.get('_csrf_token')
                or ''
            )
            # 非 ASCII 的 str 进 compare_digest 会抛 TypeError（任意匿名 POST
            # 带 `X-CSRFToken: é` 即 500），按 UTF-8 字节比较
            if not token or not secrets.compare_digest(
                    token.encode('utf-8'), expected.encode('utf-8')):
                wants_json = (
                    request.path.startswith('/api/')
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    or request.accept_mimetypes.best == 'application/json'
                )
                if not wants_json:
                    return 'CSRF 校验失败，请刷新页面后重试', 403
                return jsonify({
                    'success': False,
                    'message': 'CSRF 校验失败，请刷新页面后重试',
                    'code': 403
                }), 403
        return None

    @app.after_request
    def _set_csrf_cookie(response):
        """确保 JS 可读取 csrf_token cookie（非 HttpOnly）"""
        from flask import session
        csrf_token = session.get('csrf_token')
        if csrf_token:
            response.set_cookie(
                'csrf_token', csrf_token,
                httponly=False, samesite='Lax', secure=app.config.get('SESSION_COOKIE_SECURE', False),
                path='/'
            )
        return response

    # 注册蓝图
    from app.blueprints.auth import auth_bp
    from app.blueprints.resources import resources_bp
    from app.blueprints.exam_management import exam_mgmt_bp
    from app.blueprints.questions import questions_bp
    from app.blueprints.online_exam import online_exam_bp
    from app.blueprints.python_files import python_files_bp
    from app.blueprints.scores import scores_bp
    from app.blueprints.students import students_bp
    from app.blueprints.logs import logs_bp
    from app.blueprints.class_management import class_mgmt_bp
    from app.blueprints.attendance import attendance_bp
    from app.blueprints.classroom import classroom_bp
    from app.blueprints.student_groups import student_groups_bp
    from app.blueprints.student_drive import student_drive_bp
    from app.blueprints.homework import homework_bp
    from app.blueprints.grading import grading_bp
    from app.blueprints.ai import ai_bp
    from app.blueprints.system_settings import system_settings_bp
    from app.blueprints.teaching import teaching_bp
    from app.blueprints.activities import activities_bp
    from app.blueprints.hardware_sim import hardware_sim_bp
    from app.blueprints.chem_lab import chem_lab_bp
    from app.blueprints.sim_lab import sim_lab_bp
    from app.blueprints.teacher_home import teacher_home_bp
    from app.blueprints.surveys import surveys_bp
    from app.blueprints.student_home import student_home_bp
    from app.blueprints.admin_dashboard import admin_dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(exam_mgmt_bp)
    app.register_blueprint(questions_bp)
    app.register_blueprint(online_exam_bp)
    app.register_blueprint(python_files_bp)
    app.register_blueprint(scores_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(class_mgmt_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(classroom_bp)
    app.register_blueprint(student_groups_bp)
    app.register_blueprint(student_drive_bp)
    app.register_blueprint(homework_bp)
    app.register_blueprint(grading_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(system_settings_bp)
    app.register_blueprint(teaching_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(hardware_sim_bp)
    app.register_blueprint(chem_lab_bp)
    app.register_blueprint(sim_lab_bp)
    app.register_blueprint(teacher_home_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(student_home_bp)
    app.register_blueprint(admin_dashboard_bp)

    # 注册 API 蓝图
    from app.blueprints.api import api_bp
    app.register_blueprint(api_bp)

    # 全局错误处理 - 提升用户体验
    _register_error_handlers(app)

    # 网盘自动清理后台线程（daemon，配置驱动；界面配置即生效，无需重启）
    try:
        from app.services.drive_cleanup import start_drive_cleanup_worker
        start_drive_cleanup_worker(app)
    except Exception:
        app.logger.debug('网盘自动清理线程启动失败（已忽略）', exc_info=True)

    # AI 对话消息定期归档清理后台线程（daemon，配置驱动；界面配置即生效）
    try:
        from app.services.message_cleanup import start_message_cleanup_worker
        start_message_cleanup_worker(app)
    except Exception:
        app.logger.debug('AI消息清理线程启动失败（已忽略）', exc_info=True)

    # 弱口令告警：管理员账号仍为默认 admin/admin123 时提醒尽快修改
    try:
        from app.utils import is_default_admin_account
        if is_default_admin_account():
            app.logger.warning(
                '安全告警：管理员账号仍为默认 admin/admin123，'
                '请立即修改 admin_account.txt 后重启服务！')
    except Exception:
        app.logger.debug('管理员默认口令检查失败（已忽略）', exc_info=True)

    # 弱口令告警：数据库仍使用内置默认口令（未通过环境变量/postgresql.txt 配置）
    try:
        if app.config.get('DB_PASS') == '@@':
            app.logger.warning(
                '安全告警：数据库口令仍为内置默认值，'
                '请通过环境变量 DB_PASS 或 postgresql.txt 配置强口令！')
    except Exception:
        app.logger.debug('数据库默认口令检查失败（已忽略）', exc_info=True)

    # SPA 前端入口
    from flask import send_from_directory, redirect
    frontend_dir = os.path.realpath(os.path.join(app.config['BASE_DIR'], 'frontend'))

    @app.route('/favicon.ico')
    def favicon():
        """浏览器默认请求站点根 favicon 时返回实际图标，避免 404。"""
        return send_from_directory(app.static_folder, 'favicon.ico',
                                   mimetype='image/x-icon')

    @app.route('/app')
    def serve_spa_root():
        # 无尾斜杠访问时相对路径脚本（api/client.js、views/*.js）会解析到
        # 站点根目录 404，SPA 永远停在加载页；301 到 /app/ 使相对基准正确
        return redirect('/app/', code=301)

    @app.route('/app/')
    @app.route('/app/<path:path>')
    def serve_spa(path='index.html'):
        # 注意：不拦截 'api/' 前缀——frontend/api/*.js 是 SPA 自身的静态脚本，
        # 后端 API 位于 /api/*（独立蓝图），/app/api/* 路径不会与之冲突。
        ext = os.path.splitext(path)[1]
        if ext and ext not in ['.html', '.js', '.css']:
            path = 'index.html'
        # 防止目录穿越（send_from_directory 内部也有 safe_join，此处双重防护）。
        # 关键：Windows 上 os.path.normpath() 会把 URL 正斜杠转成反斜杠，
        # 而 werkzeug safe_join 按 URL 语义只接受正斜杠分隔的相对路径，
        # 反斜杠路径一律 NotFound → SPA 子目录资源 404。此处保持正斜杠。
        if '\\' in path or '..' in path.split('/'):
            path = 'index.html'
        safe_path = path.lstrip('/')
        # Windows 盘符/绝对路径探测防护：os.path.join(frontend_dir, 'C:/x.js')
        # 直接返回绝对路径，os.path.exists 可据 404/200 差异枚举本地磁盘文件
        # （send_from_directory 的 safe_join 虽会拒绝实际读取，存在性侧信道
        # 已泄露）。盘符/绝对路径一律归入 index.html 回退。
        if ':' in safe_path or os.path.isabs(safe_path):
            path = 'index.html'
        # 空路径（/app/）或文件不存在时回退 index.html（SPA 前端路由）
        elif not safe_path or not os.path.exists(os.path.join(frontend_dir, safe_path)):
            path = 'index.html'
        else:
            path = safe_path
        resp = send_from_directory(frontend_dir, path)
        # SPA 静态资源缓存头（此前无任何缓存策略，每次访问都重取全部脚本；
        # send_from_directory 自带 Last-Modified → 条件请求 304。业务脚本
        # 无版本参数，短缓存 10 分钟 + ETag 校验足够）
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.js', '.css'):
            resp.headers['Cache-Control'] = 'public, max-age=600'
        elif ext == '.html':
            resp.headers['Cache-Control'] = 'no-cache'
        return resp

    # 首次启动创建所有表（后续增量由 flask db upgrade 管理）
    with app.app_context():
        db.create_all()
        # 自动为已有表添加新列（migrate_db 检测 information_schema，幂等安全）
        from app.models import migrate_db, migrate_ai_credentials, create_db_indexes
        migrate_db()
        migrated_credentials = migrate_ai_credentials()
        if migrated_credentials:
            app.logger.info('已加密迁移 %d 条 AI API Key', migrated_credentials)
        # 创建缺失的性能索引（幂等安全）
        create_db_indexes()
        # 内置资源种子（幂等）：化学仿真工作台，按课堂授权范围展示
        try:
            from app.blueprints.chem_lab import ensure_chem_lab_resource
            ensure_chem_lab_resource()
        except Exception:
            db.session.rollback()
            app.logger.warning('化学仿真资源种子创建失败（跳过，下次启动重试）',
                               exc_info=True)

    # 缓存预热（避免首次请求抖动）：必须在建表之后——全新库上先预热会
    # 查询尚不存在的 subject 表，首启日志留一条误导性的 UndefinedTable 告警
    _warmup_caches(app)

    # 注：不再在启动时清除上课班级设置。原逻辑会在考试/上课中途重启后
    # 清空 active_class_id，导致全体学生被踢出且无法重登，直到管理员重新
    # 设置上课班级。上课班级应由管理员通过管理端手动切换（new_classroom_session）。

    # 上下文处理器：注入学生姓名和课堂模式到所有模板
    @app.context_processor
    def inject_globals():
        from flask import session, request
        # 登录时已将 student_name 写入 session，避免每请求查 DB
        student_name = session.get('student_name', '')
        # 欢迎横幅只在登录后的第一次页面渲染出现：读取即消费，
        # 后续点击/切换页面不再重复提示
        show_welcome = session.pop('show_welcome', False)
        classroom = request.args.get('mode') == 'classroom'
        return dict(student_name=student_name, show_welcome=show_welcome,
                    classroom_mode=classroom,
                    app_version=app.config.get('APP_VERSION', ''),
                    app_copyright=app.config.get('APP_COPYRIGHT', ''),
                    app_license=app.config.get('APP_LICENSE', ''),
                    csrf_token=session.get('csrf_token', ''))

    # ── 上传课件 HTML 适配（静态直服）──
    # 课件内部的根绝对引用（/学科资源/...）与 three CDN 在响应期映射到
    # 资源目录内的真实文件；无论从目录页内相对链接还是条目直链打开都生效。
    # 注册得比 add_cache_headers 晚 → 先执行，ETag 按改写后的内容计算。
    @app.after_request
    def _adapt_uploaded_courseware_html(response):
        try:
            from app.utils import adapt_uploaded_courseware_response
            return adapt_uploaded_courseware_response(
                response, app.static_folder)
        except Exception:
            app.logger.warning('课件 HTML 适配异常（已忽略）', exc_info=True)
            return response

    # ── 安全响应头（before_request 全局注入）──
    @app.after_request
    def add_security_headers(response):
        from flask import request as _req
        _p = _req.path or ''
        _is_hw_page = _p == '/hardware-sim' or _p.startswith('/hardware-sim/')
        _is_hw_mmake = _p.startswith('/static/hardware-sim/mmake/')
        _is_hw_esp32 = _p.startswith('/static/hardware-sim/esp32-s3/')
        _is_chem_page = _p in ('/chem-lab', '/chem-lab/')
        _is_chem_sketch = _p == '/chem-lab/sketch'
        _is_chem_static = _p.startswith('/static/chem-lab/')
        _is_chem_visual = _p.startswith('/chem-lab/visual-chem/')
        # 应用内帧（Flask 下发，含登录鉴权）：Nginx 直服 /static/ 时
        # Flask 的 CSP 不生效，经本路径保证 connect-src 收窄在所有拓扑生效
        _is_chem_frame = (
            _p in ('/chem-lab/frame', '/chem-lab/frame/')
            or (_p.startswith('/chem-lab/visual/') and _p.endswith('/frame'))
        )
        # 课件镜像帧可能被 opaque sandbox 父页嵌入（嵌套子页面/模块），
        # frame-ancestors 'self' 会把 opaque 祖先当成非 self 而拒绝加载。
        _is_courseware_frame = (_p.startswith('/study/courseware-view/')
                                or _p.startswith('/study/courseware/'))
        # clickjacking 防护：禁止被 iframe 嵌入（课件镜像帧由令牌约束）
        if not _is_courseware_frame:
            response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        # 禁止 MIME 嗅探
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        # 限制 referrer 泄露
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # 限制危险浏览器特性。硬件仿真宿主/静态页需摄像头、麦克风、
        # 定位与 Web Serial（同源 iframe 继承，direct 新窗口也生效）；
        # 其余页面维持全禁用。
        _permissions = 'geolocation=(), microphone=(), camera=(), payment=()'
        if _is_chem_page or _is_chem_sketch:
            _permissions = ('geolocation=(), microphone=(), camera=(), payment=(), '
                            'fullscreen=(self), '
                            'clipboard-read=(self), clipboard-write=(self)')
        if _is_hw_page or _is_hw_mmake or _is_hw_esp32:
            _permissions = ('geolocation=(self), microphone=(self), camera=(self), '
                            'serial=(self), payment=()')
        response.headers.setdefault('Permissions-Policy', _permissions)
        # 内容安全策略（纵深防御）：限制脚本/对象/基址/连接来源，防注入数据外泄。
        # 静态依赖以本地为首选，国内/官方 CDN 回退仍需对应 CSP 来源。
        _cdn_sources = (
            'https://cdn.bootcdn.net https://cdn.staticfile.org '
            'https://lib.baomitu.com https://npm.elemecdn.com '
            'https://cdn.jsdelivr.net https://unpkg.com '
            'https://cdn.tailwindcss.com'
        )
        _csp = ("default-src 'self'; "
                f"script-src 'self' 'unsafe-inline' {_cdn_sources}; "
                f"style-src 'self' 'unsafe-inline' {_cdn_sources}; "
                "img-src 'self' data: blob:; "
                f"font-src 'self' data: {_cdn_sources}; "
                "connect-src 'self'; "
                # worker-src：JitViewer 等文档渲染器以 blob: Worker 解析
                # office 文件；未声明时回退 script-src（无 blob:）→ 预览静默失败
                "worker-src 'self' blob:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-src 'self'; "
                "frame-ancestors 'self'; "
                "form-action 'self'")
        # /study/link 外链课件页与课堂页（/study/lesson）需 iframe 嵌入
        # 外部 URL/课件条目（sandbox 已隔离、URL 经 _is_safe_url / 编排树
        # 白名单校验），单独放行 frame-src https:，否则外链条目空白
        if _p.startswith(('/study/link', '/study/lesson')):
            _csp = _csp.replace("frame-src 'self';", "frame-src 'self' https:;")
        # /app SPA（Vue 3 全局构建，免构建部署）：组件为 template 字符串，
        # 运行时编译依赖 new Function → 必须放行 'unsafe-eval'，否则 Vue
        # 挂载抛 CSP 违规、整页白屏（真实浏览器 E2E 实证）。仅 SPA 路径
        # 放宽，其余页面维持严格 script-src。
        if _p == '/app' or _p.startswith('/app/'):
            _csp = _csp.replace("script-src 'self' 'unsafe-inline'",
                                "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
        # 硬件仿真静态页按需放宽：掌控板的仿真解释器用 new AsyncFunction，
        # 上传音频用 data: <audio>，天气/讯飞走外部 HTTPS/WSS；ESP32-S3
        # 只额外需要 Google Fonts。宿主页 /hardware-sim 不运行仿真脚本，
        # 仅放宽 Permissions-Policy，CSP 保持严格。
        if _is_hw_mmake:
            _csp = _csp.replace("script-src 'self' 'unsafe-inline'",
                                "script-src 'self' 'unsafe-inline' 'unsafe-eval'")
            _csp = _csp.replace("img-src 'self' data: blob:;",
                                "img-src 'self' data: blob:; "
                                "media-src 'self' data: blob:;")
            _csp = _csp.replace(
                "connect-src 'self';",
                "connect-src https://api.open-meteo.com "
                "https://geocoding-api.open-meteo.com "
                "https://iat-api.xfyun.cn https://tts-api.xfyun.cn "
                "https://webapi.xfyun.cn https://tupapi.xfyun.cn "
                "https://rest-api.xfyun.cn https://api.xf-yun.com "
                "wss://iat-api.xfyun.cn wss://tts-api.xfyun.cn;")
        # ESP32-S3 字体已自托管；其 fetch 只读取自身 data/firmware/reference，
        # connect-src 限定到本应用目录前缀，阻断同源 /api/ 调用。
        elif _is_hw_esp32:
            _host = _req.host_url.rstrip('/')
            _path = '/static/hardware-sim/esp32-s3/'
            _https = _host.replace('http://', 'https://', 1)
            _csp = _csp.replace(
                "connect-src 'self';",
                f"connect-src {_host}{_path} {_https}{_path};")
        # 化学仿真帧、Ketcher 编辑器与静态目录：Molstar / Ketcher / 可视化
        # 化学运行于同源上下文，connect-src 收窄到本目录前缀，阻断第三方
        # 脚本携带会话 Cookie 调同源 /api/ 等接口。帧路由由 Flask 下发，
        # 保证 Nginx 直服静态时 CSP 在所有部署拓扑下有效。
        elif _is_chem_page:
            # 宿主页只运行 3Dmol.js（WebGL），不放行 eval；
            # Ketcher/Molstar 同源 iframe 由各自 CSP 约束。
            _csp = _csp.replace(
                "connect-src 'self';",
                "connect-src 'self' data: blob:;")
        elif (_is_chem_sketch or _is_chem_static or _is_chem_frame
              or _is_chem_visual):
            # Ketcher standalone 的 Indigo WASM/Worker 与 Molstar 解析器
            # 需要 eval/wasm 编译；仅对编辑器帧、帧路由与静态目录放行。
            _csp = _csp.replace(
                "script-src 'self' 'unsafe-inline'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "'wasm-unsafe-eval'")
            _csp = _csp.replace(
                "worker-src 'self' blob:;",
                "worker-src 'self' blob: data:;")
            _host = _req.host_url.rstrip('/')
            _path = '/static/chem-lab/'
            _https = _host.replace('http://', 'https://', 1)
            _csp = _csp.replace(
                "connect-src 'self';",
                f"connect-src {_host}{_path} {_https}{_path} "
                f"{_host}/chem-lab/visual-chem/ "
                f"{_https}/chem-lab/visual-chem/ data: blob:;")
        if _is_courseware_frame:
            # 令牌已限定资源范围；opaque sandbox 祖先没有网络 scheme，
            # 无法被 frame-ancestors 的任何 source 匹配，故镜像帧不下发
            # 该指令（同时已移除 X-Frame-Options），允许嵌套子页面加载。
            # 上传课件常把 three.js/OrbitControls 内联为
            # data:text/javascript;base64 模块（importmap 或动态 import），
            # 该帧本身已是无 Cookie 的 opaque sandbox，允许 data: 脚本
            # 与既有 'unsafe-inline' 同级，不波及平台页面。
            _csp = _csp.replace(
                "script-src 'self' 'unsafe-inline'",
                "script-src 'self' 'unsafe-inline' data:")
            _csp = _csp.replace("frame-ancestors 'self'; ", "")
        response.headers.setdefault('Content-Security-Policy', _csp)
        return response

    # ── 用户上传目录访问控制（保密性）──
    # 作业提交、网盘、学生作品等目录经 Flask 静态直服匿名可读（URL 可枚举），
    # 此处对这些目录的 GET 做鉴权：
    #   管理员/教师 → 全部放行；学生 → 仅本人数据（网盘/作品/提交）与教学资料放行；
    #   未登录 → 拒绝。
    # 资源课件目录 /static/uploads/<资源名>/ 与 /static/question_img/ 保持公开。
    # 清单唯一权威源在 app/utils.py PRIVATE_UPLOAD_PREFIXES（响应缓存头
    # 同样按它判定 private/no-store——两处清单漂移会导致"鉴权放行却可被
    # 共享代理缓存"），此处仅取引用。
    _PRIVATE_UPLOAD_PREFIXES = PRIVATE_UPLOAD_PREFIXES

    def _static_forbidden():
        from flask import jsonify, request as _req
        if _req.path.startswith('/api/') or _req.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'message': '无权访问该文件'}), 403
        return '<h1>403</h1><p>无权访问该文件。</p>', 403

    @app.before_request
    def _reject_static_path_aliases():
        """拒绝空段/Windows 文件系统别名（尾点/空格、ADS、8.3 短名、设备名）。

        URL 字符串按原样做前缀/归属判定，而 Werkzeug safe_join 会 normpath
        折叠 `//`、Windows 会把这些别名解析到真实文件——不拦截时
        `/static/uploads//cloud_drive/<sid>/x` 不以私有前缀开头，鉴权直接
        放行、静态路由却折叠后提供真实文件（匿名可读他人网盘/提交/隐藏
        课件），`/static/uploads/guide.pdf.`、`.../GUIDE~1.PDF` 同理。
        """
        from flask import request as _req
        path = _req.path or ''
        if path.startswith('/static/') and (
                '//' in path or has_dot_segment(path)
                or has_win_path_alias(path)):
            return _static_forbidden()

    def _teacher_private_file_allowed(path, path_l, teacher_id):
        """教师读取私有静态文件的归属校验（与页面/下载接口同口径）。

        此前所有 is_teacher 会话（含全校共享只读码登录）可直读任意学生的
        提交/网盘/作品/Python 答案：静态钩子只判角色，绕过了 homework.py、
        student_drive.py、activities.py 的任课班级边界。这里按班级归属校验；
        教学资料（python_files/activity_docs）仍对全体教师开放。
        """
        if not teacher_id:
            return False
        if path_l.startswith(('/static/uploads/python_files/',
                              '/static/uploads/activity_docs/')):
            return True
        from app.extensions import cache as _class_cache
        class_key = f'teacher:class_ids:{teacher_id}'
        class_ids = _class_cache.get(class_key)
        if class_ids is None:
            from app.services.resource_access import teacher_class_ids as _tci
            class_ids = _tci(teacher_id)
            _class_cache.set(class_key, class_ids, timeout=30)
        if not class_ids:
            return False
        from app.models import Student as _Student
        try:
            if path_l.startswith('/static/submissions/'):
                parts = path_l.split('/')
                if len(parts) >= 4:
                    from app.models import HomeworkSubmission as _HS
                    sub = db.session.get(_HS, parse_int(parts[3]))
                    stu = db.session.get(_Student, sub.student_id) if sub else None
                    return bool(stu and stu.class_id in class_ids)
            elif path_l.startswith('/static/uploads/cloud_drive/'):
                parts = path_l.split('/')
                if len(parts) >= 5:
                    stu = db.session.get(_Student, parse_int(parts[4]))
                    return bool(stu and stu.class_id in class_ids)
            elif path_l.startswith('/static/uploads/student_works/'):
                parts = path_l.split('/')
                if len(parts) >= 6:
                    stu = db.session.get(_Student, parse_int(parts[5]))
                    return bool(stu and stu.class_id in class_ids)
            elif path_l.startswith('/static/uploads/drive/'):
                parts = path_l.split('/')
                if len(parts) >= 5:
                    from app.models import StudyGroup as _G
                    grp = db.session.get(_G, parse_int(parts[4]))
                    return bool(grp and grp.class_id in class_ids)
            elif path_l.startswith('/static/uploads/python_answers/'):
                rel = path[len('/static/uploads/python_answers/'):]
                from app.models import PythonAnswer as _PA
                ans = _PA.query.filter_by(
                    file_path=f'python_answers/{rel}').first()
                stu = db.session.get(_Student, ans.student_id) if ans else None
                return bool(stu and stu.class_id in class_ids)
        except Exception:
            return False
        return False

    @app.before_request
    def _protect_private_uploads():
        from flask import request, session
        path = request.path or ''
        # Windows 大小写不敏感：所有前缀/目录判断按小写比较，避免
        # /static/UPLOADS/CLOUD_DRIVE/... 绕过归属鉴权（实测可匿名读私有文件）
        path_l = path.lower()
        if not path_l.startswith(_PRIVATE_UPLOAD_PREFIXES):
            return None

        # 点段（'.'/'..'）穿越与 Windows 别名防护：归属检查按原始 path 段索引判定，
        # 而 Werkzeug safe_join 会 normpath 后拼接——含点段即 fail-closed，
        # 否则可用 cloud_drive/5/../6/x 折叠读取他人文件
        if has_dot_segment(path) or has_win_path_alias(path):
            return _static_forbidden()

        # 管理员可访问全部受保护目录；教师按任课班级归属放行（见上）
        if session.get('is_admin'):
            return None
        if session.get('is_teacher'):
            if _teacher_private_file_allowed(path, path_l,
                                             session.get('teacher_id')):
                return None
            return _static_forbidden()
        student_id = session.get('student_id')
        # 教学资料（题目参考文件、活动文档）：登录用户均可访问
        if path_l.startswith('/static/uploads/python_files/') or \
                path_l.startswith('/static/uploads/activity_docs/'):
            if student_id:
                return None
            return _static_forbidden()
        if not student_id:
            return _static_forbidden()

        try:
            if path_l.startswith('/static/uploads/cloud_drive/'):
                parts = path_l.split('/')
                # /static/uploads/cloud_drive/<sid>/...
                if len(parts) >= 5 and parts[4] == str(student_id):
                    return None
            elif path_l.startswith('/static/uploads/drive/'):
                parts = path_l.split('/')
                # 小组网盘：/static/uploads/drive/<gid>/...，仅组内学生可访问
                if len(parts) >= 5:
                    gid = parts[4]
                    from app.models import Student as _S
                    stu = db.session.get(_S, student_id)
                    if stu and stu.group_id is not None and str(stu.group_id) == gid:
                        # 网盘关闭后页面/下载/直链同口径：组员也不能再读
                        from app.models import StudyGroup as _G
                        grp = db.session.get(_G, stu.group_id)
                        if grp and grp.drive_enabled:
                            return None
            elif path_l.startswith('/static/uploads/student_works/'):
                parts = path_l.split('/')
                # /static/uploads/student_works/<aid>/<sid>/...
                if len(parts) >= 6 and parts[5] == str(student_id):
                    return None
            elif path_l.startswith('/static/submissions/'):
                parts = path_l.split('/')
                # /static/submissions/<sub_id>/... — 仅本人提交
                if len(parts) >= 4:
                    from app.models import HomeworkSubmission as _HS
                    sub = db.session.get(_HS, parse_int(parts[3]))
                    if sub and sub.student_id == student_id:
                        return None
            elif path_l.startswith('/static/homework/'):
                parts = path_l.split('/')
                # /static/homework/<hw_id>/... — 该作业所属班级的学生可访问。
                # 附件目录按作业 id 命名（标题可重复且可变，不可作目录名）；
                # 性能：静态文件请求高频，避免每次 2-3 次 DB 查询——
                # 学生班级缓存（TTL 120s）+ 班级可访问作业 id 集合缓存
                # （TTL 120s，一次 JOIN 构建；作业编辑/删除后最多滞后 120s）。
                if len(parts) >= 4 and parts[3].isdigit():
                    hw_id = int(parts[3])
                    from app.extensions import cache as _dir_cache
                    class_key = f'student:class:{student_id}'
                    stu_class_id = _dir_cache.get(class_key)
                    if stu_class_id is None:
                        from app.models import Student as _S2
                        stu = db.session.get(_S2, student_id)
                        if not stu or not stu.class_id:
                            return _static_forbidden()
                        stu_class_id = stu.class_id
                        _dir_cache.set(class_key, stu_class_id, timeout=120)
                    ids_key = f'homework:allowed_ids:{stu_class_id}'
                    allowed = _dir_cache.get(ids_key)
                    if allowed is None:
                        from sqlalchemy import text as _dir_text
                        # 仅放行启用（is_active=true）作业：停用作业的
                        # 附件不再可直链，与学生端页面 is_active 校验语义一致
                        rows = db.session.execute(_dir_text(
                            'SELECT hw.id FROM homework hw '
                            'JOIN homework_classes hc ON hc.homework_id = hw.id '
                            'WHERE hc.class_id = :cid AND hw.is_active = TRUE'
                        ), {'cid': stu_class_id}).all()
                        allowed = {r[0] for r in rows}
                        _dir_cache.set(ids_key, allowed, timeout=120)
                    if hw_id in allowed:
                        return None
            elif path_l.startswith('/static/uploads/python_answers/'):
                # 文件名 uuid8_xxx.py — 反查 PythonAnswer 归属。
                # rel 保留原始大小写与 DB 中存储值精确匹配（大小写变体
                # 查不到记录 → fail-closed）。
                rel = path[len('/static/uploads/python_answers/'):]
                from app.models import PythonAnswer as _PA
                ans = _PA.query.filter_by(file_path=f'python_answers/{rel}').first()
                if ans and ans.student_id == student_id:
                    return None
        except Exception:
            # 鉴权查询异常时 fail-closed：拒绝而非放行
            app.logger.debug('受保护静态目录鉴权异常（已拒绝）', exc_info=True)
            return _static_forbidden()

        return _static_forbidden()

    # ── 课件目录服务端权限强制 ──
    # /static/uploads/<资源目录>/ 对登录用户公开（供学习页内联预览），但
    # show_in_student=false 的资源与学生不可见的文件此前仅前端隐藏按钮，
    # 直链可绕过。此处对非教师/管理员请求强制校验：
    #   学生：资源须在「任课教师范围 + 公开/内置」内（教师自建资源
    #        全量、共享资源按任教学科；范围内不要求 show_in_student）
    #   匿名：资源须 show_in_student=true
    #   文件级 file_permissions show=false → 403（所有非管理角色）
    # 目录名 = secure_filename_with_unicode(title)，经缓存映射（TTL 300s，
    # 编辑/删除资源后最多滞后 5 分钟，与 homework:dir_map 策略一致）。
    # download=false 维持 UI 语义：静态内联无法阻止"另存为"，已在 /study 隐藏下载按钮。

    @app.before_request
    def _enforce_courseware_permissions():
        import json as _json
        from flask import request as _req, session as _sess
        path = _req.path or ''
        path_l = path.lower()
        if not path_l.startswith('/static/uploads/'):
            return None
        # 点段穿越防护 + Windows 别名（尾点/空格/8.3 短名等）：dir_name/rel
        # 取自未归一化路径，而静态路由会按文件系统语义解析——不拦截则
        # show=false 的资源/文件可被别名写法绕过（默认匿名可见）
        if has_dot_segment(path) or has_win_path_alias(path):
            return _static_forbidden()
        if _sess.get('is_admin'):
            return None
        if _sess.get('is_teacher') and _sess.get('teacher_mode') != 'readonly':
            return None
        # 课件公开开关（courseware_public_enabled，默认公开）：关闭后
        # 课件文件直链仅登录用户可访问（页面/预览已同步校验；此处为
        # 直链兜底，杜绝"页面关了、直链仍可下载"的绕过面）
        if not _sess.get('student_id') and not _sess.get('is_teacher'):
            from app.models import SystemConfig as _SC
            if not _SC.get_bool('courseware_public_enabled', True):
                return _static_forbidden()
        parts = path.split('/')
        if len(parts) < 4:
            return None
        dir_name = parts[3]
        try:
            from app.models import Resource as _R
            from app.utils import secure_filename_with_unicode as _sfw
            from app.extensions import cache as _res_cache
            map_key = 'courseware:dir_map'
            dir_map = _res_cache.get(map_key)
            if dir_map is None:
                # 投影查询：仅取标题/URL/可见性/文件权限列，避免全量加载
                # Text 大字段（homework_files 等）。
                # 键同时取 url 的目录段与标题清洗名：目录在上传时按标题建立，
                # 改标题不会重命名目录——只按新标题建键会查不到旧目录，
                # 落入"未知目录 → 公开"分支，隐藏资源改个名就能被直链访问。
                # 全部键统一小写：Windows 文件系统大小写不敏感，鉴权必须同口径。
                resources = _R.query.with_entities(
                    _R.id, _R.title, _R.url, _R.show_in_student,
                    _R.file_permissions, _R.allow_related_files
                ).all()
                dir_map = {}
                for res_id, title, url, show, perms, allow_related in resources:
                    keys = set()
                    if url and url.startswith('/static/uploads/'):
                        keys.add(url[len('/static/uploads/'):].split('/', 1)[0])
                    if title:
                        keys.add(_sfw(title))
                    for key in keys:
                        if key:
                            dir_map.setdefault(key.lower(), []).append(
                                (res_id, show, perms, allow_related))
                _res_cache.set(map_key, dir_map, timeout=300)
            matches = dir_map.get(dir_name.lower())
            if not matches:
                return None  # 非课件目录（未知目录名）维持原公开行为

            def _match_parts(match):
                # 兼容升级前缓存中的 3 元组（无 allow_related_files）
                if len(match) == 4:
                    return match
                res_id, show, perms = match
                return res_id, show, perms, False
            # 学生鉴权按「任课教师范围 + 公开/内置」：课堂跟随教师的资源
            # 不要求 show_in_student（教师课堂展示即授权，修复学生打开
            # PPTX/预览 403）；文件级「展示」隐藏对范围和公开资源一律生效；
            # 范围外一律拒绝。匿名访客沿用旧规则（show_in_student + 文件级 show）。
            rel = '/'.join(parts[4:])

            def _file_perm_denied(perms_json):
                if not rel:
                    return False
                try:
                    perms = _json.loads(perms_json or '{}')
                except Exception:
                    perms = {}
                # 权限键按小写比较（Windows 文件名大小写不敏感）
                rel_l = rel.lower()
                for perm_key, perm_val in perms.items():
                    if str(perm_key).lower() == rel_l:
                        return bool(perm_val and perm_val.get('show') is False)
                return False

            student_id = _sess.get('student_id')
            if _sess.get('is_teacher'):
                # 只读教师（全校访问码）必须按资源授权读取，不能再像编辑
                # 教师一样直读全部上传目录；文件级「展示」隐藏同样生效。
                from app.services.resource_access import (
                    teacher_can_use_resource, teacher_can_view)
                teacher_id = _sess.get('teacher_id')
                for match in matches:
                    res_id, _show_value, perms_json, allow_related = \
                        _match_parts(match)
                    resource = db.session.get(_R, res_id)
                    if (not resource or (_file_perm_denied(perms_json)
                                         and not allow_related)):
                        continue
                    if (teacher_can_view(resource, teacher_id,
                                         mode='readonly')
                            or resource.show_in_classroom
                            and teacher_can_use_resource(resource,
                                                         teacher_id)):
                        return None
                return _static_forbidden()
            if not student_id:
                if not all(_match_parts(match)[1] is not False
                           for match in matches):
                    return _static_forbidden()
                if any(_file_perm_denied(_match_parts(match)[2])
                       and not _match_parts(match)[3]
                       for match in matches):
                    return _static_forbidden()
                return None
            from app.models import Student as _Stu
            from app.services.resource_access import student_scope_sets
            student = db.session.get(_Stu, student_id)
            teacher_ids, public_ids = student_scope_sets(student)
            allowed = False
            for match in matches:
                res_id, _show, perms_json, allow_related = _match_parts(match)
                # 授课教师范围：不要求 show_in_student，但文件级隐藏仍拒绝
                if (res_id in teacher_ids
                        and (allow_related
                             or not _file_perm_denied(perms_json))):
                    allowed = True
                    break
                # 公开/内置资源：文件级 show=false 仍拒绝
                if (res_id in public_ids
                        and (allow_related
                             or not _file_perm_denied(perms_json))):
                    allowed = True
                    break
            if not allowed:
                return _static_forbidden()
        except Exception:
            app.logger.debug('课件权限鉴权异常（已拒绝）', exc_info=True)
            return _static_forbidden()
        return None

    # ── 用户上传目录中的主动内容防护（存储型 XSS）──
    # 学生/教师上传的作业、作品、网盘文件物理上位于 static/ 下，会被 Flask
    # 以原始 MIME 直接提供服务。若其中含 HTML/SVG/JS 等主动内容，浏览器会在
    # 应用同源下执行，配合非 HttpOnly 的 csrf_token cookie 可导致会话接管。
    # 此处对这些目录中的危险类型强制文本类型 + 附件下载，使其无法作为脚本执行。
    # 资源课件目录 /static/uploads/<资源名>/ 需内联渲染 HTML，故不在拦截之列。
    _UPLOAD_ACTIVE_CONTENT_PREFIXES = (
        '/static/submissions/', '/static/homework/', '/static/chunks/',
        '/static/uploads/drive/', '/static/uploads/cloud_drive/',
        '/static/uploads/student_works/', '/static/uploads/python_answers/',
        '/static/uploads/python_files/', '/static/uploads/activity_docs/',
        '/static/uploads/group_files/',
    )
    # 与 app/utils.py 的 DANGEROUS_INLINE_EXTS 共用同一份清单
    from app.utils import DANGEROUS_INLINE_EXTS as _DANGEROUS_INLINE_EXTS
    from app.utils import is_active_mimetype as _is_active_mimetype

    @app.after_request
    def _neutralize_uploaded_active_content(response):
        from flask import request
        try:
            path = (request.path or '').lower()
            if path.startswith(_UPLOAD_ACTIVE_CONTENT_PREFIXES):
                ext = path.rsplit('.', 1)[-1] if '.' in path else ''
                if ext in _DANGEROUS_INLINE_EXTS or _is_active_mimetype(response.mimetype):
                    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
                    response.headers['Content-Disposition'] = 'attachment'
                    response.headers['X-Content-Type-Options'] = 'nosniff'
        except Exception:
            app.logger.debug('上传主动内容防护钩子异常（已忽略）', exc_info=True)
        return response

    # ── 课件目录 CORS 放行（配合 /study/link 的 sandbox 隔离）──
    # 课件在 opaque origin 的 sandbox iframe 中运行后，其内 fetch 读取同源
    # 数据（如 /static/uploads/<课件>/data.json）会被 CORS 拦截。此处对课件
    # 目录响应放开 Access-Control-Allow-Origin:* —— 仅放行无凭据请求
    # （课件数据读取）；带凭据的请求（cookie/CSRF 代发）依 CORS 凭据规则
    # 仍被拒绝，会话防护不受影响。

    @app.after_request
    def _allow_courseware_cors(response):
        try:
            from flask import request as _req
            path = (_req.path or '').lower()
            if path.startswith('/static/uploads/') and not path.startswith(_PRIVATE_UPLOAD_PREFIXES):
                response.headers['Access-Control-Allow-Origin'] = '*'
        except Exception:
            app.logger.debug('课件 CORS 头设置异常（已忽略）', exc_info=True)
        return response

    return app


def _warmup_caches(app):
    """缓存预热：应用启动时预热高频查询缓存

    直接调用自带缓存写入的 lookup 函数（get_subjects_cached 等），
    避免旧实现的"查询后丢弃结果"空操作。
    """
    try:
        from app.utils import get_subjects_cached, get_classes_cached, get_schedules_cached
        with app.app_context():
            subjects = get_subjects_cached()
            classes = get_classes_cached()
            schedules = get_schedules_cached()
            app.logger.info(
                '缓存预热完成: subjects=%d, classes=%d, schedules=%d',
                len(subjects), len(classes), len(schedules)
            )
    except Exception as e:
        # 预热失败不能影响应用启动
        app.logger.warning('缓存预热失败（已忽略）: %s', e)


def _get_class_cached(class_id):
    """班级信息查询（带缓存穿透保护）

    对不存在的 class_id 缓存一个 '__missing__' 标记，避免反复穿透数据库。
    缓存有效期 60 秒。注意：只缓存轻量 dict 而非 ORM 实例——filesystem
    缓存 pickle 序列化后反序列化为 detached 实例，访问懒加载关系会抛
    DetachedInstanceError（此前与 utils.py 注释自相矛盾）。
    """
    from app.models import Class
    from app.utils import cache
    key = f'class:{class_id}'
    cached = cache.get(key)
    if cached == '__missing__':
        return None
    if cached is not None:
        return cached
    obj = db.session.get(Class, class_id)
    if obj is None:
        cache.set(key, '__missing__', timeout=60)
        return None
    data = {'id': obj.id, 'name': obj.name,
            'description': obj.description or ''}
    cache.set(key, data, timeout=300)
    return data


def _register_slow_query_logger(app, threshold_ms=500):
    """注册 SQLAlchemy 慢查询监听器

    通过 before_cursor_execute / after_cursor_execute 事件记录每个 SQL
    的执行耗时，超过阈值时输出警告（包含 SQL 截断与请求路径），
    便于在生产环境定位慢查询。
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    import time as _time
    from flask import request, has_request_context

    @event.listens_for(Engine, 'before_cursor_execute')
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = _time.time()

    @event.listens_for(Engine, 'after_cursor_execute')
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        total = (_time.time() - context._query_start_time) * 1000
        if total < threshold_ms:
            return
        sql_preview = statement[:200].replace('\n', ' ')
        if has_request_context():
            path = request.path
            method = request.method
            app.logger.warning(
                f"[SLOW SQL] {total:.1f}ms {method} {path} :: {sql_preview}"
            )
        else:
            app.logger.warning(f"[SLOW SQL] {total:.1f}ms :: {sql_preview}")


def _register_error_handlers(app):
    """注册全局错误处理器，提升用户友好性"""
    from flask import jsonify, request
    from werkzeug.exceptions import HTTPException

    def _wants_json():
        if request.path.startswith('/api/'):
            return True
        accept = request.accept_mimetypes
        return accept.best == 'application/json'

    @app.errorhandler(404)
    def _handle_404(error):
        if _wants_json():
            return jsonify({'success': False, 'message': '资源不存在', 'code': 404}), 404
        return ('<h1>404 页面不存在</h1>'
                '<p>您访问的页面已被删除或不存在。'
                '<a href="/">返回首页</a></p>'), 404

    @app.errorhandler(500)
    def _handle_500(error):
        app.logger.error(f"[500 ERROR] {request.path}", exc_info=True)
        if _wants_json():
            return jsonify({'success': False, 'message': '服务器内部错误', 'code': 500}), 500
        return ('<h1>500 服务器内部错误</h1>'
                '<p>系统处理请求时发生错误，请稍后重试或联系管理员。</p>'), 500

    @app.errorhandler(413)
    def _handle_413(error):
        if _wants_json():
            return jsonify({'success': False, 'message': '上传内容超过限制', 'code': 413}), 413
        return '<h1>上传内容超过限制</h1><p>请压缩文件或分批上传。</p>', 413

    @app.errorhandler(Exception)
    def _handle_exception(error):
        # 透传 werkzeug HTTPException 由具体 handler 处理
        if isinstance(error, HTTPException):
            return error
        app.logger.error(f"[UNHANDLED] {request.path}: {error}", exc_info=True)
        if _wants_json():
            return jsonify({'success': False, 'message': '系统繁忙，请稍后重试', 'code': 500}), 500
        return ('<h1>系统繁忙</h1><p>请稍后重试。</p>'), 500
