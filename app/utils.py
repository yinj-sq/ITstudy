import os
import io
import re
import time
import hashlib
import threading
import tempfile
import uuid
import secrets
import string
from urllib.parse import quote, unquote
from contextlib import contextmanager
from functools import wraps
from flask import request, url_for, current_app, jsonify
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash


def get_utc_now():
    """获取当前 UTC 时间（带时区信息）。"""
    return datetime.now(timezone.utc)


def get_local_now():
    """获取当前本地时间（学生登录时间等业务场景使用）。"""
    return datetime.now()


def generate_numeric_password(length=8):
    """生成不可预测的临时数字密码。"""
    if length < 6:
        raise ValueError('密码长度至少为6位')
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def all_chunks_present(directory, total_chunks):
    """判断分块是否全部到达；与到达顺序无关。"""
    return total_chunks > 0 and all(
        os.path.isfile(os.path.join(directory, str(index)))
        for index in range(total_chunks)
    )


def measure_time(f):
    """性能监控装饰器 - 记录超过200ms的慢请求"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        result = f(*args, **kwargs)
        elapsed_time = (time.time() - start_time) * 1000
        if elapsed_time > 200:
            current_app.logger.warning(f"性能警告: 路由 {request.path} 执行时间 {elapsed_time:.2f}ms")
        return result
    return decorated_function


def parse_int(value, default=None):
    """安全地把请求参数转为 int，失败返回 default（避免脏输入导致 500）。"""
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def excel_safe(value):
    """Excel 公式注入防护：字符串以 =、+、-、@ 开头（含前导制表符/回车变体）
    时，在前面加 ' 使其被 Excel 视为纯文本；非字符串原样返回。

    用于所有把用户可控字符串写入 Excel 单元格的位置（姓名、班级、文本等），
    数字列不要调用本函数。
    """
    if not isinstance(value, str):
        return value
    # 制表符/回车前缀会被部分 Excel 版本跳过，需一并识别
    if value.lstrip('\t\r')[:1] in ('=', '+', '-', '@'):
        return "'" + value
    return value


def json_body_or_empty():
    """读取 JSON 请求体，非对象（数组/字符串/畸形 JSON）一律返回 {}。

    顶层 list/str 为真值，`request.get_json(silent=True) or {}` 会原样返回
    list，随后 `data.get(...)` 抛 AttributeError → 500（负向扫描实证
    /api/ai/clear_session）。统一在此收敛为 dict。
    """
    from flask import request
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def paginate_query(query, default_per_page=20, max_per_page=100):
    """统一分页工具函数

    从 request.args 中提取 page 和 per_page 参数，
    对 per_page 设置上限防止滥用，返回 SQLAlchemy Pagination 对象。
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', default_per_page, type=int)
    if page < 1:
        page = 1
    # 超大 page 会算出超出 PostgreSQL int8 的 offset（offset=(page-1)*per_page）
    # 直接 DataError → 500；钳制到安全上限，超出的页码返回空页
    page = min(page, 10_000_000)
    per_page = max(1, min(per_page, max_per_page))
    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_classes_cached():
    """获取班级列表（带缓存，TTL 300s）

    返回轻量级 dict 列表（避免缓存 SQLAlchemy 模型实例，
    防止 DetachedInstanceError 和 pickle 风险）。
    """
    from app.extensions import cache
    from app.models import Class
    from types import SimpleNamespace
    key = 'lookup:classes'
    data = cache.get(key)
    if data is not None:
        return [SimpleNamespace(**item) for item in data]
    rows = Class.query.order_by(Class.name).all()
    # 用聚合计数替代 len(c.students) 全量加载学生行（含 password_hash 列）
    from sqlalchemy import func
    from app.models import Student as _Student, StudyGroup as _StudyGroup
    from app.extensions import db as _db
    class_ids = [c.id for c in rows]
    stu_counts = dict(
        _db.session.query(_Student.class_id, func.count(_Student.id))
        .filter(_Student.class_id.in_(class_ids)).group_by(_Student.class_id).all()
    ) if class_ids else {}
    grp_counts = dict(
        _db.session.query(_StudyGroup.class_id, func.count(_StudyGroup.id))
        .filter(_StudyGroup.class_id.in_(class_ids)).group_by(_StudyGroup.class_id).all()
    ) if class_ids else {}
    raw = [{
        'id': c.id,
        'name': c.name,
        'description': c.description or '',
        'student_count': stu_counts.get(c.id, 0),
        'group_count': grp_counts.get(c.id, 0),
        'create_time': c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else None
    } for c in rows]
    cache.set(key, raw, timeout=300)
    return [SimpleNamespace(**item) for item in raw]


def get_subjects_cached():
    """获取学科列表（带缓存，TTL 300s）

    返回轻量级 SimpleNamespace 列表。
    """
    from app.extensions import cache
    from app.models import Subject
    from types import SimpleNamespace
    key = 'lookup:subjects'
    data = cache.get(key)
    if data is not None:
        return [SimpleNamespace(**item) for item in data]
    rows = Subject.query.order_by(Subject.sort_order).all()
    # 用聚合计数替代 len(s.resources) 全量加载资源行
    from sqlalchemy import func
    from app.models import Resource as _Resource
    from app.extensions import db as _db
    subject_ids = [s.id for s in rows]
    res_counts = dict(
        _db.session.query(_Resource.subject_id, func.count(_Resource.id))
        .filter(_Resource.subject_id.in_(subject_ids)).group_by(_Resource.subject_id).all()
    ) if subject_ids else {}
    raw = [{
        'id': s.id,
        'name': s.name,
        'sort_order': s.sort_order,
        'resource_count': res_counts.get(s.id, 0)
    } for s in rows]
    cache.set(key, raw, timeout=300)
    return [SimpleNamespace(**item) for item in raw]


def get_schedules_cached():
    """获取作息时间表（带缓存，TTL 120s）

    返回轻量级 SimpleNamespace 列表。
    """
    from app.extensions import cache
    from app.models import Schedule
    from types import SimpleNamespace
    key = 'lookup:schedules'
    data = cache.get(key)
    if data is not None:
        return [SimpleNamespace(**item) for item in data]
    rows = Schedule.query.filter_by(is_active=True).order_by(
        Schedule.sort_order, Schedule.start_time).all()
    raw = [{
        'id': s.id,
        'period_name': s.period_name,
        'start_time': s.start_time,
        'end_time': s.end_time,
        'sort_order': s.sort_order
    } for s in rows]
    cache.set(key, raw, timeout=120)
    return [SimpleNamespace(**item) for item in raw]


def sse_bump(channel):
    """SSE 推送通道版本号 +1（原子递增，无缓存时置 1）。

    写操作后调用，EventSource 端点（/api/events/<channel>）检测到版本
    变化即推送 'refresh' 事件，前端收到后重新拉取数据（替代高频轮询）。
    零 DB 开销；缓存键 1 小时 TTL，通道闲置自动过期。
    """
    from app.extensions import cache
    try:
        ver = cache.get(f'sse:ver:{channel}') or 0
        cache.set(f'sse:ver:{channel}', ver + 1, timeout=3600)
    except Exception:
        # 缓存不可用时降级（前端保留轮询兜底），但需告警而非静默——
        # 否则缓存故障时管理员无从感知实时推送已失效
        import logging
        logging.getLogger(__name__).warning(
            'SSE 推送通道版本号写入失败（缓存不可用），实时推送降级为'
            '轮询兜底: channel=%s', channel, exc_info=True)


def invalidate_exam_list_cache():
    """试卷列表相关缓存统一失效（唯一实现）。

    覆盖：管理端/学生端试卷列表 + 导航栏"最近试卷"下拉。
    此前 api.py 与 exam_management.py 各持一份实现且键集漂移
    （后者漏 lookup:recent_exams），HTML 端建卷/改卷后导航下拉
    存在 30s 脏窗口。两条通道统一引用本函数。
    """
    from app.extensions import cache
    cache.delete('api:exams:list:admin')
    cache.delete('api:exams:list:student')
    cache.delete('lookup:recent_exams')


def invalidate_lookup_cache(*names):
    """失效查找表缓存

    names: 'classes', 'subjects', 'schedules' 中的一个或多个
    """
    from app.extensions import cache
    mapping = {
        'classes': 'lookup:classes',
        'subjects': 'lookup:subjects',
        'schedules': 'lookup:schedules',
    }
    for name in names:
        key = mapping.get(name)
        if key:
            cache.delete(key)


def get_client_ip():
    """获取客户端真实IP地址

    仅在显式配置 TRUST_PROXY_HEADERS=1（位于可信反向代理之后）时
    才读取 X-Forwarded-For 等转发头；否则直接使用 TCP 对端地址，
    避免客户端伪造转发头污染审计日志。

    配置 PROXY_SECRET（代理密钥门）后，仅携带正确 X-Proxy-Secret 头的
    请求（itstudy.trusted_proxy 标记）才采信转发头——绕过代理直连应用
    端口的请求即使伪造 XFF 也不会被采信（限流键/审计 IP 不可伪造）。
    """
    from flask import current_app
    if current_app.config.get('TRUST_PROXY_HEADERS'):
        # 代理密钥门：中间件未装时缺省 True（兼容旧行为）；装了之后以
        # 请求实际是否携带正确密钥为准
        if request.environ.get('itstudy.trusted_proxy', True):
            if request.headers.get('X-Forwarded-For'):
                # 取最后一个条目（而非首个）：nginx 用 $proxy_add_x_forwarded_for
                # 原样追加客户端 XFF 后把真实 $remote_addr 加到尾部，最左条目
                # 完全由客户端控制——取首条可让学生伪造任意 IP（自选座位号、
                # 污染审计 IP），取末条与 ProxyFix x_for=1 信任语义一致
                parts = [p.strip() for p in
                         request.headers.get('X-Forwarded-For').split(',') if p.strip()]
                if parts:
                    return parts[-1]
            if request.headers.get('X-Real-IP'):
                return request.headers.get('X-Real-IP')
            for header in ['CF-Connecting-IP', 'True-Client-IP', 'X-Client-IP']:
                if request.headers.get(header):
                    return request.headers.get(header)
    return request.remote_addr


def allowed_file(filename):
    """检查文件扩展名是否被允许"""
    from flask import current_app
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def validate_image_magic(content, filename):
    """图片扩展名的魔数校验（内容签名），防止伪装成图片的可执行内容入库。

    仅对常见图片扩展名做校验；其余类型返回 True（不做内容断言）。
    与扩展名白名单配合，构成上传内容的第一道内容级防线
    （第二道防线是 __init__.py 的危险主动内容降级下载）。
    """
    if not content:
        return False
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext == 'png':
        return content[:8] == b'\x89PNG\r\n\x1a\n'
    if ext in ('jpg', 'jpeg'):
        return content[:3] == b'\xff\xd8\xff'
    if ext == 'gif':
        return content[:6] in (b'GIF87a', b'GIF89a')
    if ext == 'bmp':
        return content[:2] == b'BM'
    if ext == 'webp':
        return content[:4] == b'RIFF' and content[8:12] == b'WEBP'
    return True


def validate_image_magic_head(file_storage, filename):
    """流式上传路径的图片魔数校验：只读文件头不整文件入内存。

    头长必须取 12 字节：webp 魔数是 RIFF(0-4) + 跳 4 字节 + WEBP(8-12)，
    只读 8 字节时 content[8:12] 恒为 b'' → 合法 webp 必被误判拒收
    （png/jpg/gif/bmp 所需字节数均 ≤8，不受影响）。
    非图片扩展名不读流，直接放行（与 validate_image_magic 口径一致）。
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
        return True
    head = file_storage.stream.read(12)
    file_storage.stream.seek(0)
    return validate_image_magic(head, filename)


# 预编译正则（上传高频路径，避免每次调用重复编译）
_RE_FILENAME_SLASH = re.compile(r'[\/\\]')
_RE_FILENAME_LEADING_DOT = re.compile(r'^\.+')
_RE_FILENAME_MULTI_DOT = re.compile(r'\.{2,}')
_RE_FILENAME_UNSAFE = re.compile(r'[^a-zA-Z0-9_一-龥぀-ゟ゠-ヿ.-]')


def secure_filename_with_unicode(filename):
    """安全处理文件名，支持中文字符。结果不会是 '.'/'..' 或以点开头。

    顺序要紧：先删非法字符、再折叠连续点、最后去前导点。此前先去前导点、
    最后才删非法字符，'#.#.' 删完 '#' 恰好剩 '..'、'!.htaccess' 剩
    '.htaccess'——调用方把结果当目录名拼路径即可跳出 static/uploads。
    """
    if not filename:
        return ''
    filename = _RE_FILENAME_SLASH.sub('_', filename)
    filename = filename.replace(' ', '_')
    filename = _RE_FILENAME_UNSAFE.sub('', filename)
    filename = _RE_FILENAME_MULTI_DOT.sub('.', filename)
    filename = _RE_FILENAME_LEADING_DOT.sub('', filename)
    if os.name == 'nt' and filename and filename.split('.')[0].upper() in (
            'CON', 'AUX', 'PRN', 'NUL',
            *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]):
        # 此前仅覆盖 COM1-4/LPT1-3，COM5.py 等在 Windows 上创建/读取失败 → 500
        filename = '_' + filename
    return filename


# 主动内容危险扩展名清单（与 __init__.py 静态目录中和钩子共用同一份，
# 防止清单漂移导致某条路径放行可执行的 HTML/JS/SVG）
DANGEROUS_INLINE_EXTS = {
    'html', 'htm', 'shtml', 'xhtml', 'xht', 'svg', 'svgz',
    'xml', 'xsl', 'xslt', 'xsd', 'rdf', 'wsdl', 'mht', 'mhtml',
    'js', 'mjs', 'htc', 'css',
}

# 浏览器会当主动内容执行/渲染的响应类型。扩展名清单永远列不全
# （.xsl/.rdf 等经 mimetypes 映射成 text/xml，XHTML 命名空间的 <script> 照样执行），
# 故静态中和钩子同时按实际下发的 MIME 判定
_ACTIVE_MIMETYPES = frozenset({
    'text/html', 'text/xml', 'application/xml', 'text/xsl',
    'text/javascript', 'application/javascript', 'application/x-javascript',
    'text/ecmascript', 'application/ecmascript',
})


def is_active_mimetype(mimetype):
    mt = (mimetype or '').split(';', 1)[0].strip().lower()
    return mt in _ACTIVE_MIMETYPES or mt.endswith('+xml')


def safe_inline_mimetype(filename):
    """用户上传的主动内容以文本预览，避免 inline HTML/JS 执行。"""
    ext = filename.rsplit('.', 1)[-1].lower() if filename and '.' in filename else ''
    if ext in DANGEROUS_INLINE_EXTS:
        return 'text/plain; charset=utf-8'
    import mimetypes
    if filename and is_active_mimetype(mimetypes.guess_type(filename)[0]):
        return 'text/plain; charset=utf-8'
    return None


class _DeleteOnCloseFile(io.FileIO):
    """关闭即删除的只读文件对象（交给 send_file 流式发送临时文件用）。

    不能用 response.call_on_close 删临时文件：send_file 设了 direct_passthrough，
    get_app_iter 直接把 WSGI 服务器的 file_wrapper 交出去、绕过挂着 _on_close 的
    ClosingIterator——Waitress 下回调**从不执行**，每次打包下载都在临时目录永久
    留下一份 zip（2026-09-27 真实起服实测复现；测试客户端走 Response.close 所以
    单测是绿的）。Waitress/werkzeug 的文件包装器关闭时都会关闭底层文件对象，
    故把删除放在这里。先关闭再删：Windows 不能删除仍打开的文件。
    """

    def close(self):
        path = self.name
        try:
            super().close()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def send_temp_zip(build, download_name):
    """在磁盘临时文件上打包 zip 并流式发送，发送结束（文件关闭）后删除。

    build(zf) 负责往 ZipFile 写条目。整份 zip 不进内存：此前作业打包/全量备份
    用 BytesIO，内存峰值约等于附件总量（几十份 50MB 作业即上 GB），并发几次即 OOM。
    conditional=True 支持 Range 断点续传。
    """
    import tempfile
    import zipfile
    from flask import send_file
    fd, tmp_path = tempfile.mkstemp(suffix='.zip')
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            build(zf)
        fobj = _DeleteOnCloseFile(tmp_path, 'r')
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    try:
        size = os.fstat(fobj.fileno()).st_size
        # 传文件对象时 werkzeug 不推断大小 → conditional 无法处理 Range（实测
        # 退回 200 全量）。先非条件发送，再按已知大小补做条件/Range 处理
        response = send_file(fobj, as_attachment=True, download_name=download_name,
                             mimetype='application/zip', conditional=False)
        response.content_length = size
        return response.make_conditional(request.environ, accept_ranges=True,
                                         complete_length=size)
    except Exception:
        fobj.close()
        raise


def strip_inline_content_disposition(response):
    """预览通道必须去掉 Content-Disposition，否则 Chromium 会吃掉响应体。

    实测矩阵（Edge headed、同源、同一路由，仅改响应头）：

        Content-Type              Content-Disposition      fetch() 结果
        application/pdf           —                        200 / 完整
        application/pdf           inline; filename=…       204 / 空
        application/octet-stream  inline; filename=…       204 / 空
        text/plain                inline; filename=…       200 / 完整
        application/pdf           attachment; filename=…  200 / 完整
        application/octet-stream  —                        200 / 完整

    即 `inline` + **非文本**类型时，Chromium 把子资源请求转交下载/插件
    通道，JS 侧只剩 204 与空 body——而服务端 after_request 记录到的仍是
    200 且带完整 Content-Length，裸 HTTP 直取也正常，故障只在浏览器侧
    可见。全站预览页都是 fetch 取 `?inline=1` 再喂 JitViewer，于是预览器
    拿到 0 字节并报「文件为空／格式不正确」。

    不能靠「不传 download_name」来省略该头：werkzeug 的 send_file 在
    path 为磁盘路径、download_name 为 None 时会用 os.path.basename(path)
    回填，Content-Disposition 照样写出。必须显式删除。

    代价：直接导航打开预览链接时「另存为」的默认名退化为 URL 末段。
    真正的下载按钮走 as_attachment=True 分支，不受影响。
    """
    response.headers.pop('Content-Disposition', None)
    return response


def versioned_static(filename):
    """添加基于文件修改时间的版本号到静态资源URL"""
    full_path = os.path.join(current_app.static_folder, filename)
    try:
        version = int(os.path.getmtime(full_path))
        return url_for('static', filename=filename, v=version)
    except Exception:
        return url_for('static', filename=filename)


# 可预压缩直出的文本类静态资源（与 tools/precompress_static.py 的清单一致）。
# 图片/字体/音视频本身已压缩，重复 gzip 无收益且浪费 CPU。
_PRECOMPRESS_EXTS = {'.js', '.css', '.json', '.map', '.svg', '.html', '.txt', '.csv'}
# 用户上传目录不参与预压缩直出：内容不可控，避免把用户提供的 .gz 当作
# 应用静态资源按 Content-Encoding: gzip 下发（课程课件仍按普通静态文件服务）。
_PRECOMPRESS_EXCLUDED_PREFIXES = ('uploads/', 'homework/', 'submissions/', 'chunks/')


def install_precompressed_static(app):
    """让 Flask 静态路由优先返回新鲜的 .gz 预压缩副本。

    背景：nginx 的 gzip_static 只在有 nginx 的部署生效；Windows 单机与
    容器默认由 Waitress 直出，9.7MB 的 jit-viewer.min.js 每次冷加载都要
    全量传输。这里在应用层做同样的事：客户端接受 gzip、且 .gz 不旧于源
    文件时直接发送，省掉每请求压缩 CPU 与传输体积。

    回退条件（任一即走原逻辑）：客户端不接受 gzip、Range 请求（Range 语义
    按编码后表示，混用易错）、非文本类型、无 .gz、.gz 比源文件旧、用户
    上传目录。异常一律回退，不影响静态服务。
    """
    import mimetypes
    from flask import send_file
    from werkzeug.security import safe_join

    static_root = os.path.realpath(app.static_folder)
    original = app.send_static_file

    def send_static_file(filename):
        try:
            rel = str(filename or '').replace('\\', '/')
            ext = os.path.splitext(rel)[1].lower()
            if (ext in _PRECOMPRESS_EXTS
                    and not rel.startswith(_PRECOMPRESS_EXCLUDED_PREFIXES)
                    and not request.headers.get('Range')
                    and request.accept_encodings['gzip']):
                src = safe_join(static_root, rel)
                gz = safe_join(static_root, rel + '.gz')
                # 新鲜度按 mtime：pack/build-installer.ps1 打包前会重建
                # 全部 .gz（--refresh-only），源文件更新而 .gz 未重建时回退
                if (src and gz and os.path.isfile(src) and os.path.isfile(gz)
                        and os.path.getmtime(gz) >= os.path.getmtime(src)):
                    mime = (mimetypes.guess_type(rel)[0]
                            or 'application/octet-stream')
                    response = send_file(gz, mimetype=mime, conditional=True)
                    response.headers['Content-Encoding'] = 'gzip'
                    response.headers.add('Vary', 'Accept-Encoding')
                    return response
        except Exception:
            app.logger.debug('预压缩静态资源回退原文件', exc_info=True)
        return original(filename)

    app.send_static_file = send_static_file


_COURSEWARE_HTML_MAX_BYTES = 8 * 1024 * 1024
_COURSEWARE_ATTR_URL_RE = re.compile(
    r'''(?P<pre>\b(?:src|href)\s*=\s*(?P<q>["']))(?P<url>/[^"'\s<>]+)'''
    r'''(?P=q)''', re.I)
_COURSEWARE_CSS_URL_RE = re.compile(
    r'''url\(\s*(?P<q>["']?)(?P<url>/[^)"'\s<>]+)(?P=q)\s*\)''', re.I)
_COURSEWARE_STRING_URL_RE = re.compile(
    r'''(?P<q>["'])(?P<url>/[^"'\r\n\\]+)(?P=q)''')
_COURSEWARE_VITE_BASE_RE = re.compile(
    r'''(?P<head>["']modulepreload["']\s*,\s*[\w$]+\s*=\s*function'''
    r'''\s*\(\s*(?P<arg>[\w$]+)\s*\)\s*\{\s*return\s*)'''
    r'''["']/["']\s*\+\s*(?P=arg)''')
_COURSEWARE_ROUTER_WINDOW_RE = re.compile(
    r'''(?P<head>function\s+[\w$]+\s*\(\{(?=[^}]*\bbasename\s*[:=])'''
    r'''(?=[^}]*\bchildren\s*[:=])[^}]*\bwindow\s*:\s*(?P<arg>[\w$]+)'''
    r'''[^}]*\}\)\s*\{)''')
THREE_CDN_MODULE_RE = re.compile(
    r'https?://(?:cdn\.jsdelivr\.net/npm|unpkg\.com)/three@[^/"\'\s)>,]+'
    r'/build/three\.module(?:\.min)?\.js', re.I)
THREE_CDN_JSM_RE = re.compile(
    r'https?://(?:cdn\.jsdelivr\.net/npm|unpkg\.com)/three@[^/"\'\s)>,]+'
    r'/examples/jsm/', re.I)
# 上传课件直接引用官方 GeoGebra 引导脚本：外网地址被 CSP 拦截且无法
# 离线运行。改写为随包副本；桥接脚本再把 applet 的 codebase 固定到本地
# 完整引擎（deployggb.js 自身默认仍指向 geogebra.org）。
GGB_CDN_DEPLOY_RE = re.compile(
    r'''(?:https?:)?//(?:www\.)?geogebra\.org/apps/deployggb\.js'''
    r'''(?:\?[^"'\s<>]*)?''', re.I)
GGB_LOCAL_DEPLOY_URL = '/static/geogebra/GeoGebra/deployggb.js'


def _courseware_abs_to_rel(url, doc_dir_parts, dir_root, *, directory=False):
    core = unquote(re.split(r'[?#]', url, 1)[0])
    if (not core or core == '/' or not core.startswith('/') or '//' in core
            or re.search(r'[\x00-\x1f\x7f]', core)
            or has_dot_segment(core) or has_win_path_alias(core)):
        return None
    if core.startswith(('/static/', '/study/', '/api/', '/chem-lab/')):
        return None
    parts = core.strip('/').split('/')
    root = os.path.realpath(dir_root)
    root_prefix = os.path.normcase(root) + os.sep
    for size in range(len(doc_dir_parts), -1, -1):
        rel_parts = doc_dir_parts[:size] + parts
        abs_path = os.path.realpath(os.path.join(root, *rel_parts))
        if (os.path.normcase(abs_path).startswith(root_prefix)
                and (os.path.isfile(abs_path)
                     or (directory and os.path.isdir(abs_path)))):
            return '/'.join(rel_parts) + ('/' if core.endswith('/') else '')
    return None


def _courseware_url_rewriter(dir_root, doc_rel_path, dir_name, target_root):
    doc_dir_parts = doc_rel_path.split('/')[:-1]
    original_root = f'/static/uploads/{dir_name}/'

    def rewrite(url, *, directory=False):
        core = re.split(r'[?#]', url, 1)[0]
        decoded = unquote(core)
        if decoded.startswith(original_root):
            rel = decoded[len(original_root):]
            abs_path = os.path.realpath(os.path.join(dir_root, rel))
            root = os.path.normcase(os.path.realpath(dir_root)) + os.sep
            if (not rel or has_dot_segment(rel) or has_win_path_alias(rel)
                    or not os.path.normcase(abs_path).startswith(root)
                    or not (os.path.isfile(abs_path)
                            or (directory and os.path.isdir(abs_path)))):
                return None
        else:
            rel = _courseware_abs_to_rel(
                core, doc_dir_parts, dir_root, directory=directory)
        if not rel:
            return None
        return target_root.rstrip('/') + '/' + quote(rel, safe='/') + url[len(core):]

    return rewrite


def adapt_courseware_script(script, dir_root, doc_rel_path, dir_name, target_root):
    rewrite = _courseware_url_rewriter(
        dir_root, doc_rel_path, dir_name, target_root)

    def string_sub(match):
        url = rewrite(match.group('url'), directory=True)
        if url is None:
            return match.group(0)
        return match.group('q') + url + match.group('q')

    script = _COURSEWARE_STRING_URL_RE.sub(string_sub, script)
    script = GGB_CDN_DEPLOY_RE.sub(GGB_LOCAL_DEPLOY_URL, script)

    def router_sub(match):
        body = script[match.end():match.end() + 400]
        factory = re.search(r'([\w$]+)\(\{\s*window\s*:\s*' +
                            re.escape(match.group('arg')) + r'\s*,\s*v5Compat\s*:', body)
        if not factory:
            return match.group(0)
        browser_history = re.search(
            r'function\s+' + re.escape(factory.group(1)) + r'\([^)]*\)\s*\{[\s\S]{0,500}?'
            r'\{\s*pathname\s*:\s*[\w$]+\s*,\s*search\s*:\s*[\w$]+\s*,\s*hash\s*:\s*[\w$]+\s*\}'
            r'\s*=\s*[^;]{0,80}\.location\s*;', script)
        if not browser_history and factory.group(1) != 'createBrowserHistory':
            return match.group(0)
        arg = match.group('arg')
        return match.group('head') + arg + '=' + arg + '||globalThis.__ITSTUDY_COURSEWARE_ROUTER_WINDOW__;'

    script = _COURSEWARE_ROUTER_WINDOW_RE.sub(router_sub, script)
    if '__vite__mapDeps' in script:
        parts = doc_rel_path.split('/')[:-1]
        if parts and parts[-1] == 'assets':
            parts.pop()
        package_root = target_root.rstrip('/') + '/' + quote('/'.join(parts), safe='/')
        package_root = package_root.rstrip('/') + '/'
        # Vite 的预加载基址独立于 import.meta.url，不能只修正入口标签。
        script = _COURSEWARE_VITE_BASE_RE.sub(
            lambda m: m.group('head') + repr(package_root) + '+' + m.group('arg'),
            script)
    return script


def adapt_courseware_css(css, dir_root, doc_rel_path, dir_name, target_root):
    rewrite = _courseware_url_rewriter(
        dir_root, doc_rel_path, dir_name, target_root)

    def css_sub(match):
        url = rewrite(match.group('url'))
        if url is None:
            return match.group(0)
        q = match.group('q')
        return f'url({q}{url}{q})'

    return _COURSEWARE_CSS_URL_RE.sub(css_sub, css)


def adapt_courseware_html(html, dir_root, doc_rel_path, dir_name,
                          static_prefix='/static/uploads', *, target_root=None):
    target_root = target_root or static_prefix.rstrip('/') + '/' + quote(dir_name, safe='')
    rewrite = _courseware_url_rewriter(
        dir_root, doc_rel_path, dir_name, target_root)
    rewritten = 0
    html, n_ggb = GGB_CDN_DEPLOY_RE.subn(GGB_LOCAL_DEPLOY_URL, html)
    rewritten += n_ggb

    def attr_sub(match):
        nonlocal rewritten
        url = rewrite(match.group('url'))
        if url is None:
            return match.group(0)
        rewritten += 1
        return match.group('pre') + url + match.group('q')

    html = _COURSEWARE_ATTR_URL_RE.sub(attr_sub, html)

    def inline_script_sub(match):
        nonlocal rewritten
        script = adapt_courseware_script(
            match.group(2), dir_root, doc_rel_path, dir_name, target_root)
        if script != match.group(2):
            rewritten += 1
        return match.group(1) + script + match.group(3)

    html = re.sub(r'(<script\b(?![^>]*\bsrc\s*=)[^>]*>)([\s\S]*?)(</script\s*>)',
                  inline_script_sub, html, flags=re.I)
    adapted = adapt_courseware_css(html, dir_root, doc_rel_path, dir_name, target_root)
    if adapted != html:
        rewritten += 1
    html = adapted
    html, n_module = THREE_CDN_MODULE_RE.subn(
        '/study/three/0.186.1/build/three.module.js', html)
    html, n_jsm = THREE_CDN_JSM_RE.subn(
        '/study/three/0.186.1/examples/jsm/', html)
    rewritten += n_module + n_jsm
    if (n_module or n_jsm) and 'importmap' not in html.lower():
        importmap = ('<script type="importmap">{"imports":{"three":'
                     '"/study/three/0.186.1/build/three.module.js",'
                     '"three/addons/":"/study/three/0.186.1/examples/jsm/"}}'
                     '</script>')
        matched = re.search(r'<head\b[^>]*>', html, re.I)
        at = matched.end() if matched else 0
        html = html[:at] + importmap + html[at:]
    return html, rewritten


def adapt_uploaded_courseware_response(response, static_folder):
    """静态直服上传课件 HTML 的适配入口（after_request 钩子调用）。

    任何路径打开的上传 HTML（目录页内的相对链接、课堂条目直链）都经过
    这里，避免只有桥接路由/条目入口才适配。仅处理 text/html 且大小受限；
    无法安全解码或无需改写时原样返回。
    """
    if request.method != 'GET' or response.status_code != 200:
        return response
    path = request.path or ''
    if (not path.lower().startswith('/static/uploads/')
            or not path.lower().endswith(('.html', '.htm'))):
        return response
    if 'text/html' not in (response.headers.get('Content-Type') or '').lower():
        return response
    length = response.content_length
    if length is None or length <= 0 or length > _COURSEWARE_HTML_MAX_BYTES:
        return response
    parts = path.split('/')
    if len(parts) < 5:
        return response
    dir_name = parts[3]
    rel_path = '/'.join(parts[4:])
    if (not dir_name or not rel_path
            or has_dot_segment(rel_path) or has_win_path_alias(rel_path)
            or has_dot_segment(dir_name) or has_win_path_alias(dir_name)):
        return response
    uploads_root = os.path.realpath(os.path.join(static_folder, 'uploads'))
    dir_root = os.path.realpath(os.path.join(uploads_root, dir_name))
    if not os.path.normcase(dir_root).startswith(
            os.path.normcase(uploads_root) + os.sep):
        return response

    if response.direct_passthrough:
        response.direct_passthrough = False
    try:
        data = response.get_data()
    except RuntimeError:
        return response
    if not data:
        return response

    charset = 'utf-8'
    declared = re.search(
        br'charset\s*=\s*["\']?\s*([\w.-]+)', data[:2048], re.I)
    if declared:
        candidate = declared.group(1).decode('ascii', 'ignore')
        try:
            import codecs
            codecs.lookup(candidate)
            charset = candidate
        except LookupError:
            pass
    try:
        if (charset.lower() in ('utf-8', 'utf8')
                and data.startswith(b'\xef\xbb\xbf')):
            html = data.decode('utf-8-sig')
        else:
            html = data.decode(charset)
    except (UnicodeDecodeError, ValueError):
        response.set_data(data)
        return response

    html, rewritten = adapt_courseware_html(
        html, dir_root, rel_path, dir_name)
    if not rewritten:
        response.set_data(data)
        return response
    response.set_data(html.encode('utf-8'))
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    # 内容已变化：缓存校验器由 add_cache_headers 按新内容重算。
    response.headers.pop('ETag', None)
    response.headers.pop('Last-Modified', None)
    return response


def extract_possible_integer_division_expressions(text):
    """从混合字符串中提取可能的整数除法表达式"""
    result = []
    patterns = [
        r'[a-zA-Z0-9_]+\s*//\s*\d+',
        r'\(\s*[^)]+\s*\)\s*//\s*\d+',
        r'[a-zA-Z0-9_]+\s*//\s*[a-zA-Z0-9_]+',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            match = match.strip()
            if match and match not in result:
                result.append(match)
    return result


def get_special_markers(content):
    """从内容中提取特殊标记（①②③等）"""
    if not content:
        return []
    original_markers = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    unicode_markers = ["①", "②", "③", "④", "⑤",
                       "⑥", "⑦", "⑧", "⑨", "⑩"]
    ascii_alternatives = ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)", "(9)", "(10)"]
    marker_id_map = {}
    for i, marker in enumerate(original_markers):
        marker_id_map[marker] = i + 1
        marker_id_map[unicode_markers[i]] = i + 1
        marker_id_map[ascii_alternatives[i]] = i + 1
    found_markers = []
    for char in content:
        if char in marker_id_map:
            found_markers.append(char)
    for alt in ascii_alternatives:
        if alt in content:
            found_markers.append(alt)
    return found_markers


def add_cache_headers(response):
    """为静态资源添加分级缓存控制头（after_request 钩子）"""
    try:
        _add_cache_headers_impl(response)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            'add_cache_headers 异常（已忽略，响应正常返回）', exc_info=True
        )
    return response


# 私有上传目录前缀（唯一权威清单，app/__init__.py 的静态鉴权钩子引用同一份）：
# 这些路径的响应按归属鉴权放行，必须禁止共享缓存（nginx proxy_cache/校内透明
# 代理）跨用户缓存回放，浏览器侧也不得强缓存（共用电脑登出后不留他人副本）。
PRIVATE_UPLOAD_PREFIXES = (
    '/static/submissions/',
    '/static/homework/',
    '/static/chunks/',
    '/static/uploads/drive/',
    '/static/uploads/cloud_drive/',
    '/static/uploads/student_works/',
    '/static/uploads/python_answers/',
    '/static/uploads/python_files/',
    '/static/uploads/activity_docs/',
)


def has_dot_segment(path):
    """路径中是否含 '.'/'..' 段、反斜杠或百分号编码的点段。

    静态目录的归属鉴权按原始 path 的段索引判定（如 cloud_drive/<sid>），
    而 Werkzeug 的 safe_join 会先 posixpath.normpath 再拼接——请求
    /static/uploads/cloud_drive/5/../6/x 能通过"第 5 段 == 自己 id"的
    检查，随后被折叠为 6/x 而提供他人文件（waitress 会 percent-decode
    但不归一化点段，故 curl --path-as-is / %2e%2e 可直达）。
    同理课件目录 show_in_student / file_permissions 校验也会因
    dir_name、rel 取自未归一化路径而失效。凡含点段一律 fail-closed。
    """
    if '\\' in path:
        return True
    for seg in path.split('/'):
        if seg in ('.', '..'):
            return True
        # 解码后仍带 %2e 属双重编码，normpath 不识别但统一拒绝更稳
        if '%2e' in seg.lower():
            return True
    return False


# Windows 设备名（Win32 在任意目录都会解析为设备，`static/uploads/CON`
# 可能打开控制台设备而非同名文件）
_WIN_DEVICE_NAMES = (
    {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)}
)
# 8.3 短名别名（如 CLOUD_~1、PROGRA~1）：NTFS 可能用短名解析到真实文件，
# 而鉴权按 URL 段名判断会把它当成未知目录放行。
_WIN_SHORT_NAME_RE = re.compile(r'^[^.]{1,8}~[0-9]{1,6}(?:\.[^.]{0,3})?$', re.I)


def has_win_path_alias(path):
    """静态路径是否含 Windows 文件系统别名（大小写以外的解析差异）。

    Windows 上以下写法都会命中真实文件，但 URL 字符串与文件系统语义不同：
      - 段尾的点/空格被 Win32 剥离（guide.pdf. / guide.pdf ）
      - 冒号开启 NTFS 备用数据流（guide.pdf::$DATA）或盘符
      - 8.3 短名（CLOUD_~1）
      - 设备名（CON/NUL/COM1…）
    大小写差异由调用方统一 lower() 后比较；本函数只负责上述"别名"形态。
    """
    for seg in str(path or '').split('/'):
        if not seg:
            continue
        if seg.endswith(('.', ' ')) or ':' in seg:
            return True
        if _WIN_SHORT_NAME_RE.match(seg):
            return True
        if seg.split('.', 1)[0].upper() in _WIN_DEVICE_NAMES:
            return True
    return False



def _add_cache_headers_impl(response):
    # Windows 文件系统大小写不敏感：缓存分级必须按小写 URL 判定，否则
    # /static/UPLOADS/cloud_drive/... 会落入 public 强缓存分支（私有文件
    # 可被共享代理缓存回放），与静态鉴权钩子同口径。
    p = (request.path or '').lower()
    if p.startswith('/static/'):
        # 私有上传目录最先判定并短路：不进入下方任何 public 强缓存分支，
        # 也不做全文 ETag（流式大文件免内存读）。此前命中图片分支会得到
        # Cache-Control: public, max-age=2592000，共享代理可缓存他人私有文件
        if p.startswith(PRIVATE_UPLOAD_PREFIXES):
            response.cache_control.no_store = True
            response.cache_control.private = True
            return
        has_version = 'v' in request.args
        is_long_term_cacheable = False

        # 对于直接流式传输的响应（如大文件），跳过 ETag 计算
        if not response.is_streamed and not response.direct_passthrough:
            try:
                data = response.get_data()
                if data:
                    etag = hashlib.sha256(data).hexdigest()
                    response.set_etag(etag)
                    if 'Vary' in response.headers:
                        if 'Accept-Encoding' not in response.headers['Vary']:
                            response.headers['Vary'] = response.headers['Vary'] + ', Accept-Encoding'
                    else:
                        response.headers['Vary'] = 'Accept-Encoding'
            except RuntimeError:
                pass

        # .html 入口（如 /static/pptist/index.html）单独 no-cache：
        # 升级构建产物后哈希资源名变化，客户端若缓存旧入口页会引用已删除
        # 的旧资源 → 白屏（AITP 踩坑 F1）
        if p.endswith('.html'):
            response.cache_control.no_cache = True
            response.cache_control.public = False
            return

        # ESP32-S3 构建产物 assets/ 文件名带内容哈希，无 ?v= 也可安全长缓存
        if (p.startswith('/static/hardware-sim/esp32-s3/assets/')
                and any(p.endswith(ext) for ext in ('.js', '.css'))):
            response.cache_control.max_age = 31536000
            response.cache_control.public = True
            response.cache_control.immutable = True
            return

        if has_version and any(p.endswith(ext) for ext in
                               ['.css', '.js', '.woff', '.woff2', '.ttf', '.svg', '.eot', '.webp']):
            response.cache_control.max_age = 63072000
            response.cache_control.public = True
            response.cache_control.immutable = True
            is_long_term_cacheable = True
        elif any(p.endswith(ext) for ext in
                 ['.css', '.js', '.woff', '.woff2', '.ttf', '.svg', '.eot']):
            # 带版本参数（versioned_static 的 v=）才允许 90 天强缓存；
            # 未带版本直引的资源（可能被遗漏引用）最长缓存 10 分钟，
            # 避免改版后浏览器最长 90 天不更新
            if has_version:
                response.cache_control.max_age = 7776000
                response.cache_control.public = True
                response.cache_control.immutable = True
            else:
                response.cache_control.max_age = 600
                response.cache_control.public = True
            is_long_term_cacheable = True
        elif any(p.endswith(ext) for ext in
                 ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
            if has_version:
                response.cache_control.max_age = 15552000
                response.cache_control.public = True
                response.cache_control.immutable = True
                is_long_term_cacheable = True
            else:
                response.cache_control.max_age = 2592000
                response.cache_control.public = True
                is_long_term_cacheable = True
        elif p.endswith('.ico'):
            response.cache_control.max_age = 2592000
            response.cache_control.public = True
            is_long_term_cacheable = True
        elif p.endswith('.map'):
            response.cache_control.max_age = 604800
            response.cache_control.public = True
        elif p.startswith('/static/uploads/') and p.endswith('.json'):
            # 课件目录下的 JSON 是课堂衍生数据（PPTist 课件缓存 / 思维导图），
            # 会被教师随时改写——禁止 24h 启发式强缓存（否则编辑保存后
            # 放映仍命中浏览器旧缓存）
            response.cache_control.no_cache = True
        else:
            response.cache_control.max_age = 86400
            response.cache_control.public = True

        if is_long_term_cacheable:
            response.cache_control.must_revalidate = True

    elif p.startswith('/uploads/'):
        response.cache_control.max_age = 604800
        response.cache_control.private = True
        if not response.is_streamed and not response.direct_passthrough:
            try:
                data = response.get_data()
                if data:
                    etag = hashlib.sha256(data).hexdigest()
                    response.set_etag(etag)
            except RuntimeError:
                pass

    elif 'text/html' in response.content_type:
        response.cache_control.no_store = True
        response.cache_control.no_cache = True
        response.cache_control.private = True
        response.cache_control.must_revalidate = True
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Vary'] = 'Cookie'

    return response


def get_admin_account_file():
    """获取管理员账号文件路径。

    默认位于项目根目录（Windows 安装形态）。容器部署用环境变量
    ADMIN_ACCOUNT_FILE 指向持久卷（compose 设 /app/instance/admin_account.txt）：
    根目录不在卷内，容器重建后账号文件丢失，管理员改过的密码随之失效。
    """
    override = os.environ.get('ADMIN_ACCOUNT_FILE', '').strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'admin_account.txt')


def get_initial_password_file():
    """首次生成的初始密码提示文件（与账号文件同目录、同 ACL）。

    Windows 服务方式安装时进程没有可读控制台，随机初始密码若只 print 到
    stdout 会永久丢失（SCM 启动的进程不保留控制台输出，logs/app.log 又按
    安全要求不记录明文密码），管理员将无法完成首次登录。此文件保存**一次性**
    明文密码，ACL 收紧为仅 SYSTEM/Administrators 可读；首次管理员登录成功后
    立即删除，后续改密/重置也会清除。
    """
    return os.path.join(os.path.dirname(get_admin_account_file()),
                        'admin_account.initial.txt')


_admin_cache = {'path': None, 'mtime': 0, 'username': None, 'password_hash': None}


def _restrict_account_file_acl(path):
    """限制账号文件 ACL（仅 SYSTEM/Administrators 可读）。

    Windows 上 os.chmod 0o600 不生效（继承父目录 ACL，同机其他用户可读
    哈希后离线爆破），需用 icacls 显式设置；POSIX 用 chmod 0o600。
    """
    if os.name == 'nt':
        try:
            import subprocess as _sp
            _sp.run(
                ['icacls', path, '/inheritance:r',
                 '/grant:r', 'SYSTEM:(R)', 'Administrators:(R)'],
                check=True, capture_output=True, timeout=15)
            return
        except Exception:
            # icacls 不可用/失败时降级保留现状（不阻断启动；
            # 若文件无法读取将 fail-closed 拒绝登录，日志可见）
            pass
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def _clear_initial_password_file():
    """删除一次性初始密码提示文件（不存在/无权限时静默忽略）。"""
    try:
        os.remove(get_initial_password_file())
    except OSError:
        pass


def _write_initial_password_file(password):
    """原子写入一次性初始密码提示文件；写盘/改权限失败返回 None。"""
    path = get_initial_password_file()
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(password + '\n')
        _restrict_account_file_acl(tmp)
        os.replace(tmp, path)
        _restrict_account_file_acl(path)
        return path
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


def _write_admin_account(username, password_hash):
    """原子写入管理员账号，磁盘上只保存密码哈希。"""
    account_file = get_admin_account_file()
    os.makedirs(os.path.dirname(account_file), exist_ok=True)
    tmp_file = account_file + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{username}\n{password_hash}\n')
    _restrict_account_file_acl(tmp_file)
    os.replace(tmp_file, account_file)
    # 替换后原文件继承旧 ACL，对目标文件再设一次（POSIX replace 保留 inode 权限）
    _restrict_account_file_acl(account_file)
    # 账号密码已变更/重置：旧的一次性初始密码提示文件立即失效
    _clear_initial_password_file()
    _admin_cache.update(path=None, mtime=0, username=None, password_hash=None)


def read_admin_account():
    """读取管理员账号文件，返回 ``(username, password_hash)``。

    兼容旧版明文文件：首次读取时立即原子迁移为 Werkzeug 密码哈希。
    使用 mtime 缓存避免热路径重复磁盘 I/O；文件被修改后自动失效。
    """
    account_file = get_admin_account_file()
    # 存量文件 ACL 回溯收紧（仅首次执行一次，幂等）：此前 ACL 只在写入
    # 路径设置，升级前已存在的 admin_account.txt 仍继承父目录 ACL——
    # 同机非管理员账户可读取/覆写密码哈希。文件不存在时由下方初始化
    # 路径写入并收紧。
    if os.path.exists(account_file) and not _admin_cache.get('acl_hardened'):
        _restrict_account_file_acl(account_file)
        _admin_cache['acl_hardened'] = True
    if not os.path.exists(account_file):
        # 安全初始化：生成随机密码，绝不再落盘 admin/admin123 弱口令。
        # 密码不写入日志（日志目录 ACL 不收紧）：服务方式安装没有可读控制台，
        # 因此另存一份一次性提示文件（同目录、同 ACL），首次登录成功后删除。
        # 部署方也可用环境变量 ADMIN_INIT_PASSWORD 预置初始密码（存在时
        # 不生成随机值，密码由部署者自定、不产生提示文件）。
        import logging as _logging
        preset = os.environ.get('ADMIN_INIT_PASSWORD', '').strip()
        random_pw = preset if preset else secrets.token_urlsafe(12)
        _write_admin_account('admin', generate_password_hash(random_pw))
        if preset:
            _logging.getLogger('app.utils').warning(
                '管理员账号文件不存在，已按 ADMIN_INIT_PASSWORD 创建账号'
                '（请立即登录后修改密码）')
        else:
            # 控制台输出便于 run_zh.bat / docker logs 直接查看；
            # 服务安装时控制台不可见，靠提示文件传递（首次登录后自动删除）
            password_file = _write_initial_password_file(random_pw)
            if password_file:
                _logging.getLogger('app.utils').warning(
                    '管理员账号文件不存在，已生成随机初始密码并保存到 %s'
                    '（仅此一次写入，首次管理员登录成功后自动删除；'
                    '请登录后立即修改密码）', password_file)
            else:
                _logging.getLogger('app.utils').warning(
                    '管理员账号文件不存在，已生成随机初始密码（提示文件写入'
                    '失败，仅输出到本控制台一次；请立即登录并修改密码）')
            try:
                print(f'管理员初始密码: {random_pw}（仅此一次输出，'
                      '请立即登录并修改密码）', flush=True)
            except Exception:
                pass
    try:
        mtime = os.path.getmtime(account_file)
    except OSError:
        mtime = 0
    if (account_file == _admin_cache['path'] and mtime
            and mtime == _admin_cache['mtime']
            and _admin_cache['username'] is not None):
        return _admin_cache['username'], _admin_cache['password_hash']
    with open(account_file, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
    # 格式损坏（不足两行：username + password_hash）时 fail-closed：
    # 拒绝认证并告警，绝不回退到公开默认口令 admin/admin123（旧实现会把
    # 截断文件静默重置为默认弱口令并写盘，等于给任意人留后门）。
    if len(lines) < 2 or not lines[0].strip() or not lines[1].strip():
        import logging as _logging
        _logging.getLogger('app.utils').error(
            '管理员账号文件损坏（缺少用户名或密码行），已拒绝认证。'
            '请修复 admin_account.txt 后重启服务。')
        raise ValueError('管理员账号文件损坏')
    username = lines[0].strip()
    stored_password = lines[1].strip()
    if not stored_password.startswith(('scrypt:', 'pbkdf2:')):
        # 旧版明文密码（两行明文格式）合法，迁移为哈希并写盘
        stored_password = generate_password_hash(stored_password)
        _write_admin_account(username, stored_password)
        mtime = os.path.getmtime(account_file)
    _admin_cache['path'] = account_file
    _admin_cache['mtime'] = mtime
    _admin_cache['username'] = username
    _admin_cache['password_hash'] = stored_password
    return username, stored_password


def password_fingerprint(password_hash):
    """会话里保存的密码指纹：密码被改/重置后与旧会话不一致 → 旧会话失效。

    会话是签名 Cookie，改密本身不会让已签发的会话作废——先用共享初始密码
    登录的人，在本人改密后会话照样有效（且改密前被强制改密挡住的限制
    也随之解除）。Flask 会话 Cookie 只签名不加密、客户端可读，故取哈希的
    二次摘要而非哈希原文片段。
    """
    if not password_hash:
        return ''
    return hashlib.sha256(str(password_hash).encode('utf-8')).hexdigest()[:16]


def session_password_matches(current_fp):
    """比对会话指纹与账号当前指纹。会话里没有指纹（升级前签发）时补写并放行。"""
    from flask import session
    sess_fp = session.get('pwd_fp')
    if sess_fp is None:
        session['pwd_fp'] = current_fp
        return True
    return secrets.compare_digest(sess_fp.encode('utf-8'), current_fp.encode('utf-8'))


def verify_admin_account(username, password):
    """以常量时间哈希校验管理员凭据。

    多账号（V5.0）：优先查 admin_account 表；表无匹配时回退文件账号
    （admin_account.txt，旧部署平滑升级路径）。文件损坏（fail-closed）
    时拒绝登录并记录告警日志。登录成功返回该账号对象（表账号）或
    ('file', None)——供调用方记录显示名/最近登录。
    """
    from app.models import AdminAccount
    account = None
    try:
        account = AdminAccount.query.filter_by(
            username=str(username).strip()).first()
    except Exception:
        account = None  # 表不可用（迁移前）回退文件
    if account is not None:
        if account.is_active and account.check_password(str(password)):
            # 首次登录成功：一次性初始密码提示文件已完成使命
            _clear_initial_password_file()
            return True, ('table', account)
        if account.is_active:
            return False, ('table', account)
        # 被停用的表账号不直接拒绝：若与文件账号同名（升级共存场景），
        # 停用表账号不应遮蔽文件兜底——继续走文件验证
        account = None

    # 文件账号兜底（旧部署兼容）
    try:
        stored_username, password_hash = read_admin_account()
    except (ValueError, OSError):
        import logging as _logging
        _logging.getLogger('app.utils').exception('管理员账号文件不可用，拒绝登录')
        return False, ('file', None)
    import secrets
    # 字节比较：非 ASCII 的 str 进 compare_digest 抛 TypeError（中文用户名登录即 500）
    username_ok = secrets.compare_digest(str(username).encode('utf-8'),
                                         stored_username.encode('utf-8'))
    try:
        password_ok = check_password_hash(password_hash, str(password))
    except (ValueError, TypeError):
        password_ok = False
    if username_ok and password_ok:
        # 首次登录成功：一次性初始密码提示文件已完成使命
        _clear_initial_password_file()
        return True, ('file', None)
    return False, ('file', None)


def is_default_admin_account():
    """管理员账号是否仍为默认弱口令 admin/admin123。"""
    try:
        username, password_hash = read_admin_account()
        return username == 'admin' and check_password_hash(password_hash, 'admin123')
    except Exception:
        return False


# ── 管理员登录失败限流 ─────────────────────────────────────
# 仅对管理员登录限流；学生常处于 NAT 后共享出口 IP，不做 IP 限流以免整班被封。
# 以 request.remote_addr（TCP 对端 / ProxyFix 校正后地址）为键，避免 X-Forwarded-For 伪造绕过。
# 计数存于共享缓存（Flask-Caching filesystem），多进程部署下计数一致；
# 缓存不可用时回退进程内存（与原行为一致）。
# 三类身份共用一套节流器（kind 区分命名空间）：
#   admin   —— 仅按 IP 计（管理员登录本身有远程开关 + 默认弱口令告警）
#   student —— 账号维度（IP+学号/姓名，8 次）+ IP 全局维度（50 次）：
#              校园 NAT 出口同 IP，只按 IP 封会把全班一起锁死；只按账号封
#              则可用「对全班账号依次试常见弱口令」横向枚举。两维并用。
#   teacher —— 同 student（IP+用户名 + IP 全局）
_LOGIN_LOCK = threading.RLock()
_login_attempts = {}  # key -> [fail_count, window_start_ts, blocked_until_ts, escalation]


@contextmanager
def _rate_limit_process_lock():
    """跨进程串行化限流缓存的读改写（FileSystemCache/同机多进程）。

    SimpleCache 是进程内缓存，多进程本就各自计数；共享缓存后端
    （filesystem）下 get→改→set 不是原子的，并发失败会丢更新（阈值被
    放大）。用临时目录下的单字节文件锁串行化；跨主机多实例请改用
    Redis 原子 INCR（本函数只解决同机多进程）。
    锁不可用时降级为无锁（不影响登录可用性）。
    """
    lock_path = os.path.join(tempfile.gettempdir(), 'itstudy_login_rate.lock')
    fh = None
    locked = False
    try:
        try:
            fh = open(lock_path, 'a+b')
            if os.name == 'nt':
                import msvcrt
                fh.seek(0, 2)
                if fh.tell() == 0:
                    fh.write(b'\0')
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            locked = True
        except Exception:
            # 锁不可用：降级为无锁，不影响登录可用性
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
                fh = None
        yield
    finally:
        if fh is not None and locked:
            try:
                if os.name == 'nt':
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass
_ADMIN_LOGIN_MAX_FAILS = 8
_ADMIN_LOGIN_WINDOW = 600   # 固定统计窗口（秒）——窗口内失败次数达到阈值即封禁
_ADMIN_LOGIN_BLOCK = 300    # 触发后统一封锁时长（秒，不再指数升级）
_STUDENT_LOGIN_MAX_FAILS = 8


def _ip_global_max_fails():
    """学生/教师单出口 IP 全局失败上限（横向枚举防护）。
    经 instance/deploy.conf 的 login_ip_global_max_fails 可调
    （校级代理场景建议 100-150）；请求上下文外回退默认 50。"""
    from flask import current_app
    try:
        return int(current_app.config.get('LOGIN_IP_GLOBAL_MAX_FAILS', 50))
    except RuntimeError:   # 无应用上下文（脚本/CLI 调用）
        return 50


def _rate_key(kind, key):
    return f'{kind}:login:fail:{key}'


def _rate_get(kind, key):
    from app.extensions import cache
    return cache.get(_rate_key(kind, key))


def _rate_set(kind, key, rec):
    from app.extensions import cache
    # 缓存 TTL 覆盖统计窗口 + 封锁时长 + 余量。封锁统一 300 秒后，
    # 960s 已覆盖「窗口 600s + 封锁 300s + 60s」；避免缓存提前过期
    # 导致计数/escalation 丢失。
    cache.set(_rate_key(kind, key), rec, timeout=_ADMIN_LOGIN_WINDOW + _block_seconds(4) + 60)


def _block_seconds(_escalation):
    """封锁时长统一 300 秒（此前 300→600→1200→2400 指数升级，用户反馈
    等待过久；escalation 参数保留用于记录连续封锁次数）。"""
    return _ADMIN_LOGIN_BLOCK


def _login_blocked_seconds(kind, key):
    """返回 (kind, key) 剩余封锁秒数（>0 表示仍在封锁中）。"""
    if not key:
        return 0
    now = time.time()
    try:
        rec = _rate_get(kind, key)
        if rec and rec[2] and rec[2] > now:
            return int(rec[2] - now)
        return 0
    except Exception:
        pass
    with _LOGIN_LOCK:
        rec = _login_attempts.get((kind, key))
        if rec and rec[2] > now:
            return int(rec[2] - now)
    return 0


def _norm_acct(account):
    """限流账号维度归一：去空白 + 小写 + 截断 64——防变体字符串重置计数
    （认证本身精确匹配，变体尝试必然失败，但会稀释账号维度的计数语义）"""
    return str(account or '').strip().lower()[:64]


def _login_register_failure(kind, key, max_fails):
    """记录一次登录失败；固定窗口内超过阈值则封锁。返回剩余封锁秒数。

    缓存路径的 get→改→set 必须与内存回退共用同一把进程内锁：48 线程并发
    提交错误口令时，无锁读改写会丢失更新（48 次失败只记 1 次），实测可把
    8 次阈值放大到约 48 倍；多实例部署仍需 Redis/DB 原子计数。
    """
    if not key:
        return 0
    now = time.time()
    with _LOGIN_LOCK:
        # 共享缓存后端（filesystem/Redis 同机）下 get→改→set 需要跨进程
        # 串行化；SimpleCache 为进程内缓存，文件锁仅增加微小开销。
        with _rate_limit_process_lock():
            try:
                rec = _rate_get(kind, key)
                # 新窗口：窗口过期且（无封禁或封禁已解除）时重置计数与 escalation。
                # 此前 rec[2] 写入后永不归零，封禁过期后窗口不重置——任何一次新失败
                # 立即再次封禁（现封锁统一 300s），合法用户错输一次即被反复封锁。
                if not rec or ((now - rec[1]) >= _ADMIN_LOGIN_WINDOW
                               and (not rec[2] or rec[2] < now)):
                    rec = [0, now, 0, 0]
                rec[0] += 1
                if rec[0] >= max_fails:
                    rec[2] = now + _block_seconds(rec[3])
                    rec[3] = min(rec[3] + 1, 4)
                _rate_set(kind, key, rec)
                if rec[2] > now:
                    # 封锁触发告警（在 _rate_set 之后：current_app 依赖请求上下文，
                    # 放前面会在无上下文的单测/后台调用中抛异常中断计数）
                    try:
                        from flask import current_app
                        # %r：key 含用户输入的用户名/学号，repr 转义换行，防伪造日志行
                        current_app.logger.warning(
                            '登录限流封锁触发: kind=%s key=%r 窗口内失败%d次，封锁%ds',
                            kind, key, rec[0], int(rec[2] - now))
                    except Exception:
                        pass
                return int(max(0, rec[2] - now))
            except Exception:
                pass  # 缓存不可用，回退内存态

        rec = _login_attempts.get((kind, key))
        if not rec or ((now - rec[1]) >= _ADMIN_LOGIN_WINDOW
                       and (not rec[2] or rec[2] < now)):
            rec = [0, now, 0, 0]
        rec[0] += 1
        if rec[0] >= max_fails:
            rec[2] = now + _block_seconds(rec[3])
            rec[3] = min(rec[3] + 1, 4)
        _login_attempts[(kind, key)] = rec
        # 清理过期项，避免字典无界增长
        if len(_login_attempts) > 4096:
            stale = [k for k, v in _login_attempts.items()
                     if v[2] < now and (now - v[1]) > _ADMIN_LOGIN_WINDOW]
            for k in stale:
                _login_attempts.pop(k, None)
        return int(max(0, rec[2] - now))


def _login_register_success(kind, key):
    """登录成功后清除该维度的失败计数。"""
    if not key:
        return
    try:
        from app.extensions import cache
        cache.delete(_rate_key(kind, key))
    except Exception:
        pass
    with _LOGIN_LOCK:
        _login_attempts.pop((kind, key), None)


# ── 管理员：仅按 IP（保留原函数名，调用方不变）──

def admin_login_blocked_seconds(ip):
    """返回该 IP 剩余封锁秒数（>0 表示仍在封锁中）。"""
    return _login_blocked_seconds('admin', ip)


def admin_login_register_failure(ip):
    """记录一次管理员登录失败；固定窗口内超过阈值则封锁。返回剩余封锁秒数。"""
    return _login_register_failure('admin', ip, _ADMIN_LOGIN_MAX_FAILS)


def admin_login_register_success(ip):
    """登录成功后清除该 IP 的失败计数。"""
    _login_register_success('admin', ip)


# ── 学生/教师：三维限流（IP+账号 / 纯账号 / IP 全局）──
#   IP+账号维度：防单 IP 爆破单账号
#   纯账号维度：防换 IP 爆破单账号（NAT 下攻击者换出口即可重置 IP 维度）
#   IP 全局维度：防「对全班账号依次试常见弱口令」横向枚举
#   任一维度封锁即封锁；登录成功仅清除账号两个维度（IP 全局保留，
#   避免单个账号登录成功即重置攻击者对全班的枚举进度）。

def student_login_blocked_seconds(ip, account):
    """学生登录剩余封锁秒数。"""
    if not ip:
        return 0
    a = _norm_acct(account)
    return max(_login_blocked_seconds('student', f'{ip}:{a}'),
               _login_blocked_seconds('student', f'account:{a}'),
               _login_blocked_seconds('student', f'ip:{ip}'))


def student_login_register_failure(ip, account):
    """记录一次学生登录失败，返回剩余封锁秒数。"""
    if not ip:
        return 0
    a = _norm_acct(account)
    # 记录失败来源 IP 索引：管理员重置密码时需要清除这些 IP 上的
    # IP+账号 / IP 全局维度封锁（学生可能不在上次成功登录的 IP 上）。
    try:
        from app.extensions import cache
        ips_key = f'student:login:fail_ips:{a}'
        ips = list(cache.get(ips_key) or [])
        if ip not in ips:
            ips = (ips + [ip])[-5:]
            cache.set(ips_key, ips,
                      timeout=_ADMIN_LOGIN_WINDOW + _block_seconds(4) + 60)
    except Exception:
        pass
    r1 = _login_register_failure('student', f'{ip}:{a}',
                                 _STUDENT_LOGIN_MAX_FAILS)
    r2 = _login_register_failure('student', f'account:{a}',
                                 _STUDENT_LOGIN_MAX_FAILS)
    g = _login_register_failure('student', f'ip:{ip}', _ip_global_max_fails())
    return max(r1, r2, g)


def student_login_register_success(ip, account):
    """学生登录成功后清除账号维度失败计数。"""
    a = _norm_acct(account)
    _login_register_success('student', f'{ip}:{a}')
    _login_register_success('student', f'account:{a}')
    try:
        from app.extensions import cache
        cache.delete(f'student:login:fail_ips:{a}')
    except Exception:
        pass


def student_login_clear_throttle(student_number='', name='', ips=()):
    """管理员重置学生密码后清除登录封锁，允许学生立即重新登录。

    学生可能用学号或姓名登录，两个账号维度都要清除；同时清除最近登录
    IP、本次管理操作 IP 以及历史失败来源 IP（失败时记录的索引）的
    IP+账号维度及 IP 全局维度（校内 NAT 场景下全班共用出口，仅清账号键
    时 IP 全局封锁仍会拦住学生）。仅由管理员密码重置路径调用。
    """
    ip_set = {str(ip).strip() for ip in ips if str(ip or '').strip()}
    for ident in {_norm_acct(student_number), _norm_acct(name)}:
        if not ident:
            continue
        try:
            from app.extensions import cache
            index_key = f'student:login:fail_ips:{ident}'
            for ip_key in (cache.get(index_key) or []):
                if str(ip_key or '').strip():
                    ip_set.add(str(ip_key).strip())
            cache.delete(index_key)
        except Exception:
            pass
    for ident in {_norm_acct(student_number), _norm_acct(name)}:
        if not ident:
            continue
        _login_register_success('student', f'account:{ident}')
        for ip_key in ip_set:
            _login_register_success('student', f'{ip_key}:{ident}')
    for ip_key in ip_set:
        _login_register_success('student', f'ip:{ip_key}')


def teacher_login_blocked_seconds(ip, username):
    """教师登录剩余封锁秒数。"""
    if not ip:
        return 0
    u = _norm_acct(username)
    return max(_login_blocked_seconds('teacher', f'{ip}:{u}'),
               _login_blocked_seconds('teacher', f'account:{u}'),
               _login_blocked_seconds('teacher', f'ip:{ip}'))


def teacher_login_register_failure(ip, username):
    """记录一次教师登录失败，返回剩余封锁秒数。"""
    if not ip:
        return 0
    u = _norm_acct(username)
    r1 = _login_register_failure('teacher', f'{ip}:{u}',
                                 _STUDENT_LOGIN_MAX_FAILS)
    r2 = _login_register_failure('teacher', f'account:{u}',
                                 _STUDENT_LOGIN_MAX_FAILS)
    g = _login_register_failure('teacher', f'ip:{ip}', _ip_global_max_fails())
    return max(r1, r2, g)


def teacher_login_register_success(ip, username):
    """教师登录成功后清除账号维度失败计数。"""
    u = _norm_acct(username)
    _login_register_success('teacher', f'{ip}:{u}')
    _login_register_success('teacher', f'account:{u}')


# ── 文件存储工具：替代 LargeBinary，存磁盘 ────────────────

def _get_upload_folder(app_config=None):
    """获取上传根目录"""
    if app_config is None:
        from flask import current_app
        try:
            return current_app.config['UPLOAD_FOLDER']
        except RuntimeError:
            pass
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, 'static', 'uploads')
    return app_config.get('UPLOAD_FOLDER')


def _safe_join_under(base_dir, *paths):
    """安全拼接路径，确保目标始终位于 base_dir 内。"""
    base_real = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base_real, *paths))
    if target != base_real and not target.startswith(base_real + os.sep):
        raise ValueError('非法文件路径')
    return target


def save_stream_to_disk(file_storage, subdir, filename, max_bytes=None):
    """流式保存上传文件（file_storage.save 直接落盘，不整文件读入内存）。

    此前各上传点 file.read(max+1) 把整个文件读入内存，20-200MB 文件在
    48 线程并发下内存峰值显著（单请求 = 文件大小）。save 后按 getsize
    校验超限并删除已写文件，磁盘无残留。

    Returns: (ok, message, relative_path, size_bytes)
    """
    upload_folder = _get_upload_folder()
    target_dir = _safe_join_under(upload_folder, subdir)
    os.makedirs(target_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:8]}_{secure_filename(filename)}"
    abs_path = _safe_join_under(target_dir, unique_name)
    try:
        file_storage.save(abs_path)
    except Exception:
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
        except OSError:
            pass
        return False, '文件保存失败', None, 0
    size = os.path.getsize(abs_path)
    if max_bytes is not None and size > max_bytes:
        try:
            os.remove(abs_path)
        except OSError:
            pass
        return False, f'单个文件不能超过 {max_bytes // (1024 * 1024)}MB', None, 0
    rel_path = os.path.join(subdir, unique_name).replace('\\', '/')
    return True, '', rel_path, size


def save_file_to_disk(file_content, subdir, filename):
    """保存文件到磁盘，返回相对路径（相对 UPLOAD_FOLDER）

    Args:
        file_content: bytes 或 str（str 会自动编码为 UTF-8）
        subdir: 子目录名（如 'python_files', 'python_answers', 'drive/<组ID>'）
        filename: 文件名

    Returns:
        相对路径字符串，如 'python_files/abc123_file.py'
    """
    upload_folder = _get_upload_folder()
    target_dir = _safe_join_under(upload_folder, subdir)
    os.makedirs(target_dir, exist_ok=True)

    # 生成唯一文件名（前缀 + 安全的原名）
    unique_name = f"{uuid.uuid4().hex[:8]}_{secure_filename(filename)}"
    abs_path = _safe_join_under(target_dir, unique_name)

    if isinstance(file_content, str):
        file_content = file_content.encode('utf-8')

    with open(abs_path, 'wb') as f:
        f.write(file_content)

    # 返回正斜杠相对路径（跨平台一致）
    return os.path.join(subdir, unique_name).replace('\\', '/')


def read_file_from_disk(relative_path):
    """从磁盘读取文件内容，返回 bytes"""
    upload_folder = _get_upload_folder()
    abs_path = _safe_join_under(upload_folder, relative_path)
    with open(abs_path, 'rb') as f:
        return f.read()


def get_file_absolute_path(relative_path):
    """获取文件绝对路径（用于 send_file 等）"""
    upload_folder = _get_upload_folder()
    return _safe_join_under(upload_folder, relative_path)


def compress_image_file(abs_path, max_width=800, quality=80):
    """Pillow 压缩图片并原位覆盖（宽超限等比缩到 max_width，JPEG quality 80）。

    用于题目图片等"展示用"上传：此前原图直存，5MB 相机原图 × 数百题
    存储占用显著、列表/预览页全量传输原图。压缩失败返回 False（调用方
    保留原图，不影响上传）；GIF 跳过（保留动图）。
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(abs_path) as im:
            fmt = (im.format or '').upper()
            if fmt == 'GIF':
                return False
            if im.width > max_width:
                ratio = max_width / im.width
                im = im.resize(
                    (max_width, max(1, int(im.height * ratio))),
                    getattr(Image, 'Resampling', Image).LANCZOS
                )
            if fmt in ('JPEG', 'JPG'):
                im = im.convert('RGB')
                im.save(abs_path, 'JPEG', quality=quality, optimize=True)
            else:
                im.save(abs_path, fmt, optimize=True)
            return True
    except Exception:
        return False


def get_existing_absolute_path(relative_path):
    """返回磁盘直送下载用的绝对路径；文件缺失或路径非法时返回 None。

    大文件下载统一走磁盘直送（send_file 绝对路径 + conditional=True），
    不再全文件读入内存再 BytesIO 中转（此前缺陷：200MB 文件单请求内存
    峰值 ≥200MB，48 线程并发有 OOM 风险；直送还获得 Range/304 支持）。
    """
    try:
        abs_path = get_file_absolute_path(relative_path)
        return abs_path if os.path.isfile(abs_path) else None
    except (ValueError, FileNotFoundError):
        return None


def delete_file_from_disk(relative_path):
    """安全删除磁盘文件"""
    if not relative_path:
        return
    upload_folder = _get_upload_folder()
    abs_path = _safe_join_under(upload_folder, relative_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)


def _quiz_collector_block(resource_id, source_file=''):
    """生成受管采集块；BEGIN/END 标记便于后续更新或移除。"""
    import json as _json
    rid = resource_id if resource_id else 0
    src = str(source_file or '').replace('\\', '/').lstrip('/')
    # 路径虽来自服务端校验，仍防止 </script> 截断内联脚本
    rid_js = _json.dumps(rid)
    src_js = _json.dumps(src, ensure_ascii=False).replace('</', '<\\/')
    return (
        '<!-- ITSTUDY_QUIZ_COLLECTOR:BEGIN -->\n'
        '<script>\n'
        'window.__INJECT_RESOURCE_ID__ = ' + rid_js + ';\n'
        'window.__ITSTUDY_QUIZ_SOURCE_FILE__ = ' + src_js + ';\n'
        '</script>\n'
        '<script src="/static/sdk/collector-base.js"></script>\n'
        '<script src="/static/sdk/quiz-collector.js"></script>\n'
        '<script>\n'
        '(function () {\n'
        '  function start() {\n'
        '    if (window.QuizCollector) QuizCollector.init(' + rid_js + ');\n'
        '  }\n'
        '  if (document.readyState === "loading") {\n'
        '    document.addEventListener("DOMContentLoaded", start);\n'
        '  } else { start(); }\n'
        '})();\n'
        '</script>\n'
        '<!-- ITSTUDY_QUIZ_COLLECTOR:END -->'
    )


_QUIZ_COLLECTOR_BLOCK_RE = re.compile(
    r'<!--\s*ITSTUDY_QUIZ_COLLECTOR:BEGIN\s*-->.*?'
    r'<!--\s*ITSTUDY_QUIZ_COLLECTOR:END\s*-->',
    re.IGNORECASE | re.DOTALL)


def inject_quiz_collector(filepath, resource_id=None, source_file=None):
    """在 HTML 文件中注入答题采集 SDK（磁盘持久化注入）。

    新格式使用受管 BEGIN/END 注释块，重复应用时会更新 resource_id 与
    source_file，而不是直接跳过。历史版本的
    `<!-- ITSTUDY_QUIZ_COLLECTOR -->` 标记仍视为已注入（返回 False），
    调用方可用 is_html_injected() 将其视为成功。

    Returns:
        bool: 本次是否写入/更新了文件
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return False

    block = _quiz_collector_block(resource_id, source_file)
    if _QUIZ_COLLECTOR_BLOCK_RE.search(content):
        updated = _QUIZ_COLLECTOR_BLOCK_RE.sub(lambda _m: block, content, count=1)
        if updated == content:
            return False
    elif 'ITSTUDY_QUIZ_COLLECTOR' in content:
        # 旧版非受管块：已有采集脚本，避免重复插入
        return False
    else:
        updated = content

    backup_path = filepath + '.bak'
    if updated is not content:
        # 仅在首次注入时保留原始备份；后续更新不覆盖原始 .bak
        if not os.path.exists(backup_path):
            try:
                import shutil
                shutil.copy2(filepath, backup_path)
            except Exception:
                pass  # 备份失败不阻塞注入
        return _write_injected_file(filepath, updated, backup_path)

    if '</head>' in updated.lower():
        updated = re.sub(
            r'</head>', lambda _m: block + '\n</head>',
            updated, count=1, flags=re.IGNORECASE
        )
    elif '<body' in updated.lower():
        updated = re.sub(
            r'(<body[^>]*>)', lambda m: m.group(1) + '\n' + block,
            updated, count=1, flags=re.IGNORECASE
        )
    else:
        updated = block + '\n' + updated

    if not os.path.exists(backup_path):
        try:
            import shutil
            shutil.copy2(filepath, backup_path)
        except Exception:
            pass
    return _write_injected_file(filepath, updated, backup_path)


def _write_injected_file(filepath, content, backup_path):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        # nginx gzip_static 可能仍下发旧 .gz；内容变化后删除，让其重新压缩/直发
        try:
            if os.path.isfile(filepath + '.gz'):
                os.remove(filepath + '.gz')
        except OSError:
            pass
        return True
    except Exception:
        # 回滚：从备份恢复
        try:
            if os.path.exists(backup_path):
                import shutil
                shutil.copy2(backup_path, filepath)
        except Exception:
            pass
        return False


def is_html_injected(filepath):
    """检查 HTML 文件是否已注入 SDK

    读全文件（与 inject_quiz_collector 的判重口径一致）：此前只读前
    4096 字节，head 内联样式超 4KB 的页面（</head> 在 4KB 之后）会被
    误判"已还原"，回滚端点跳过导致采集器永久残留。
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return 'ITSTUDY_QUIZ_COLLECTOR' in f.read()
    except Exception:
        return False


def revert_html_injection(filepath):
    """从 .bak 备份还原 HTML 文件（撤销注入）"""
    backup_path = filepath + '.bak'
    if not os.path.exists(backup_path):
        return False, '备份文件不存在'
    try:
        import shutil
        shutil.copy2(backup_path, filepath)
        try:
            if os.path.isfile(filepath + '.gz'):
                os.remove(filepath + '.gz')
        except OSError:
            pass
        return True, '已还原'
    except Exception as e:
        return False, str(e)


def api_error(message, code=400, status_code=None, **extra):
    """统一 API 错误响应构造器

    提供给所有 API 端点一致的错误响应格式，便于前端做通用错误处理。
    """
    payload = {'success': False, 'message': message, 'code': code}
    payload.update(extra)
    return jsonify(payload), status_code or 400


def api_success(data=None, message='ok', **extra):
    """统一 API 成功响应构造器"""
    payload = {'success': True, 'message': message, 'data': data}
    payload.update(extra)
    return jsonify(payload)


def pagination_payload(pagination, items_serializer, base_url=None, **params):
    """统一分页响应负载构造

    pagination: Flask-SQLAlchemy Pagination 对象
    items_serializer: 列表项序列化函数
    base_url: 用于构造翻页链接；如未提供则返回 page 数字，由前端自行组装
    """
    import urllib.parse

    def _build(page):
        if not base_url:
            return page
        query = dict(params)
        query['page'] = page
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        return f'{base_url}?{qs}' if qs else base_url

    return {
        'items': [items_serializer(item) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'has_prev': pagination.has_prev,
        'has_next': pagination.has_next,
        'prev_url': _build(pagination.prev_num) if pagination.has_prev else None,
        'next_url': _build(pagination.next_num) if pagination.has_next else None,
    }
