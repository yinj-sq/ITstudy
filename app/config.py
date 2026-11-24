"""ITstudy 配置模块 — 版权所有 (C) 2025-2026 YINJUN"""
import logging
import math
import os
import re
import tempfile
from urllib.parse import quote_plus


# ── 产品版本 ──
APP_VERSION = '6.1.1'
APP_COPYRIGHT = 'Copyright (C) 2025-2026 YINJUN'
APP_LICENSE = '仅供个人学习使用，商用请联系权利人 YINJUN'

# Waitress 工作线程数：单进程并发能力（deploy.conf: waitress_threads）
WAITRESS_THREADS_DEFAULT = 48
WAITRESS_THREADS_MIN = 8
WAITRESS_THREADS_MAX = 128

_PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _restrict_key_file_acl(key_file):
    """收紧 SECRET_KEY 文件 ACL（幂等，Windows icacls / POSIX chmod）。"""
    try:
        from app.utils import _restrict_account_file_acl
        _restrict_account_file_acl(key_file)
    except Exception:
        try:
            os.chmod(key_file, 0o600)
        except (OSError, NotImplementedError):
            pass  # 失败降级，不影响启动


def _load_or_create_secret_key(base_dir):
    """读取持久化的 SECRET_KEY；首次运行时生成并写入 instance/secret_key。

    避免每次进程重启都生成新 key 导致已登录用户全部掉线。
    """
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    key_file = os.path.join(instance_dir, 'secret_key')
    if os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key:
            # 存量文件 ACL 回溯收紧（升级部署）：此前仅在新建路径执行，
            # V4.x 升级到 V5.0 的旧 key 文件保持继承 ACL（同机非管理员
            # 可读 SECRET_KEY → 伪造管理员会话）。幂等执行。
            _restrict_key_file_acl(key_file)
            return key
    key = os.urandom(32).hex()
    with open(key_file, 'w', encoding='utf-8') as f:
        f.write(key)
    # Windows 上 chmod 0o600 无效：复用 icacls 收紧为仅 SYSTEM/Administrators
    # 可读（与 admin_account.txt 同策略），防同机其他账户读 SECRET_KEY 伪造会话
    _restrict_key_file_acl(key_file)
    return key


def _load_db_settings(base_dir):
    """加载数据库连接配置。

    优先级：环境变量 > 安装向导写入的 postgresql.txt > 内置默认值。
    NSIS 安装程序会在安装目录写入 postgresql.txt（每行 key=value），
    此处读取它，使安装向导中填写的数据库信息真正生效。
    """
    defaults = {'host': 'localhost', 'port': '5432', 'dbname': 'itstudy',
                'user': 'postgres', 'password': '@@'}
    file_cfg = {}
    for candidate in (os.path.join(base_dir, 'postgresql.txt'),
                      os.path.join(base_dir, 'instance', 'postgresql.txt')):
        if os.path.exists(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        key, value = line.split('=', 1)  # 密码可能含 '='，仅按首个分隔
                        file_cfg[key.strip().lower()] = value.strip()
                break
            except Exception:
                pass  # 读取失败时回退到环境变量/默认值

    def pick(env_key, file_key):
        return os.environ.get(env_key) or file_cfg.get(file_key) or defaults[file_key]

    return {
        'host': pick('DB_HOST', 'host'),
        'port': pick('DB_PORT', 'port'),
        'name': pick('DB_NAME', 'dbname'),
        'user': pick('DB_USER', 'user'),
        'password': pick('DB_PASS', 'password'),
    }


# ── 部署调优参数 ─────────────────────────────────────
# 统一入口 instance/deploy.conf（key=value，与 postgresql.txt 同风格）。
# 优先级：系统环境变量 > deploy.conf > 内置默认值。
# 首次启动自动生成带注释的模板文件；修改后重启服务生效。
# 数据库连接仍走 postgresql.txt / 环境变量 DB_*（安装向导已写入）。
DEPLOY_CONF_TEMPLATE = """# ITstudy 部署调优参数（instance/deploy.conf）
# 优先级：系统环境变量 > 本文件 > 内置默认值
# 修改后需重启 ITstudy 服务生效（服务模式：services.msc 重启；
# 命令行模式：重新运行 run_zh.bat）
# 数据库连接请在 postgresql.txt 或环境变量 DB_* 中配置（安装向导已写入）
# 会话密钥：默认使用 instance/secret_key（安装时自动生成）；多实例共享
# 会话时请统一设置环境变量 SECRET_KEY（否则各实例登录态互不相认）

# 缓存后端：SimpleCache（单进程默认，亚毫秒级读写）/ FileSystemCache（多进程部署）
# 旧写法 simple / filesystem 同样可用（应用启动时自动换算成类名）
cache_type=SimpleCache

# 缓存目录（filesystem 后端时生效）
# cache_dir=data/cache

# HTTPS 反向代理部署时设 1（Session Cookie 仅 HTTPS 传输）
# cookie_secure=1

# Host 头白名单（逗号分隔的主机名/IP，两侧空格忽略；留空=不校验）。
# 禁止携带端口——条目带端口将与请求 Host（已剥端口）永不匹配，全站 400。
# /api/healthz 豁免（本机/容器探活走 127.0.0.1，无需列入）
# trusted_hosts=192.168.9.105,localhost

# 位于可信反向代理之后时设 1（信任 X-Forwarded-For/X-Real-IP，
# 否则所有客户端共享代理 IP 作为限流键/审计 IP）
# trust_proxy_headers=1

# 代理密钥（可选，建议与 trust_proxy_headers=1 同设）：
# 反向代理在每个请求上加请求头 X-Proxy-Secret: <本值>（如 nginx 的
# proxy_set_header X-Proxy-Secret "xxx"），应用仅对携带正确密钥的请求
# 采信 X-Forwarded-*（ProxyFix），其余（绕过代理直连应用端口）保持
# TCP 对端地址——否则内网主机可直连 :5000 并伪造 XFF 头，绕过
# "管理员远程登录已关闭"开关、逐请求换新登录限流的 IP 维度、伪造
# 座位号/考勤/审计 IP。未设置时保持旧行为（信任所有请求的 XFF）。
# 值请用长随机串（python -c "import secrets;print(secrets.token_urlsafe(32))"）
# proxy_secret=

# 学生自定义 AI 地址允许访问的私网（校内模型，逗号分隔主机名/IP；
# 默认全禁）。端口会被忽略——按主机放行该主机的所有端口，
# 请确保目标主机仅运行可信的模型服务
# student_ai_private_hosts=192.168.1.10

# 登录失败单出口 IP 全局上限（学生/教师横向枚举防护）。
# 校园 NAT 出口共享 IP 属正常形态，默认 50 适用于普通场景；
# 若全校经校级代理/大 NAT 上网（登录失败计数被多个班级共享），
# 可调至 100-150 降低误锁概率
# login_ip_global_max_fails=50

# 全进程 AI 流式对话并发上限。Waitress 一线程一连接：每次流式请求在上游
# 生成期间（最长 180s，见 app/blueprints/ai.py 的 _STREAM_TOTAL_SECONDS）
# 占用一个线程，一班学生同时提问即可吃满默认 48 线程池（waitress_threads
# 可调），令其余页面/心跳/提交
# 请求全部排队。超出本限额的流式请求快速返回"繁忙"（HTTP 429），宁个别
# AI 请求稍后重试，也不让全站不可用。
# 默认 48 线程时可设 12-20（按 180s 占用复核：20 × 180s 仍可能长期占满，
# 建议先设 12 并观察日志中的 429 比例）；线程池调大后再按比例上调。
# 管理端「系统开关」页可在运行时覆盖本值（写入 system_config），留空恢复
# 这里的部署默认值。
# ai_max_concurrent_streams=16

# Waitress 工作线程数（单进程并发能力，默认 48，范围 8-128）。
# 每个线程同一时刻服务一个请求；调高后可承载更多并发，但线程内的数据库
# 访问各占一个连接——应用连接池会按本值自动放大（约 1.25 倍），请确认
# PostgreSQL max_connections 足够（默认 100，需留出管理/备份连接余量）。
# 管理端「系统设置」页可直接修改本项；修改后需重启 ITstudy 服务生效。
# waitress_threads=48

# 逐题分析结果短缓存（秒）。同一资源同一来源页在 TTL 内复用聚合结果；
# 成绩提交/删除、学生或资源删除会立即让该资源的缓存失效。0 关闭缓存
# quiz_analysis_cache_seconds=45

# 大文件下载专用线程池。仅对附件下载生效：并发名额用尽快速返回 503 +
# Retry-After，不排队占用 Waitress 线程；内联预览/视频 Range 流不占用名额。
# 0 关闭专用池（全部下载退回原 send_file 路径）
# large_download_pool_size=8

# 进入下载专用池的文件大小阈值（MB）。仅附件下载且文件达到该大小时生效；
# 0 关闭阈值（等同关闭专用池）
# large_download_threshold_mb=16
"""


_DEPLOY_KEY_RE = re.compile(r'^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=')


def _deploy_template_blocks():
    """把 DEPLOY_CONF_TEMPLATE 按空行切成块，返回 [(key, 块文本), ...]。

    每块 = 一段说明注释 + 其后的配置行（生效的 `key=` 或注释掉的 `# key=`）。
    键取块内**最后**一个匹配行——说明注释在前、配置行在末是模板的固定写法，
    取末行可避免说明文字里出现 `xxx=` 时误判。纯说明块（文件头）键为 None。
    """
    blocks = []
    for raw in DEPLOY_CONF_TEMPLATE.strip('\n').split('\n\n'):
        key = None
        for line in raw.splitlines():
            m = _DEPLOY_KEY_RE.match(line)
            if m:
                key = m.group(1).lower()
        blocks.append((key, raw))
    return blocks


def _merge_missing_deploy_blocks(conf_path, text):
    """把模板中存量文件缺失的配置块追加到 deploy.conf 末尾。

    升级场景：模板只在文件**不存在**时整份写出，因此老部署的 deploy.conf
    会永远停留在安装时的键集——本轮新增的 ai_max_concurrent_streams 之类
    调优项既没有注释说明、也没有可取消注释的样例行，运维只能靠读源码才
    知道它存在（此前每新增一个键就要手工同步每台机器的配置文件）。
    这里按"键是否以任何形式（生效行或注释行）出现过"判断缺失，缺则连同
    说明注释整块追加，幂等且不触碰用户已改过的行。

    @return: 追加后的完整文本；无缺失时返回原文本（不写盘）
    """
    present = set()
    for line in text.splitlines():
        m = _DEPLOY_KEY_RE.match(line)
        if m:
            present.add(m.group(1).lower())
    missing = [blk for key, blk in _deploy_template_blocks()
               if key and key not in present]
    if not missing:
        return text
    merged = text.rstrip('\n') + '\n\n' + '\n\n'.join(missing) + '\n'
    try:
        with open(conf_path, 'w', encoding='utf-8') as f:
            f.write(merged)
    except OSError:
        return text  # 无写入权限：本次仍按原文本取值，不影响启动
    return merged


def _load_deploy_settings(base_dir):
    """加载部署调优参数：首次运行自动生成模板文件，返回 {key: value}（键小写）。

    存量文件缺少新版本新增的配置块时自动补齐（见 _merge_missing_deploy_blocks），
    保证升级后运维能在同一个文件里看到全部可调项及其说明。
    """
    deploy_cfg = {}
    conf_path = os.path.join(base_dir, 'instance', 'deploy.conf')
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    if not os.path.exists(conf_path):
        try:
            with open(conf_path, 'w', encoding='utf-8') as f:
                f.write(DEPLOY_CONF_TEMPLATE)
        except OSError:
            pass  # 无写入权限时静默回退到默认值
    if os.path.exists(conf_path):
        try:
            with open(conf_path, 'r', encoding='utf-8') as f:
                text = f.read()
            # 补齐新增配置块：**独立 try**——合并只是为运维补文档，
            # 出任何意外都不该连累下面的取值解析（否则整份 deploy.conf
            # 静默失效、全部回退默认值，比缺几行注释严重得多）
            try:
                text = _merge_missing_deploy_blocks(conf_path, text)
            except Exception:
                pass
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)  # 值可能含 '='，仅按首个分隔
                deploy_cfg[key.strip().lower()] = value.strip()
        except Exception:
            pass  # 读取失败回退到环境变量/默认值
    return deploy_cfg


def _deploy_conf_path(base_dir=None):
    return os.path.join(base_dir or _PROJECT_ROOT, 'instance', 'deploy.conf')


def read_deploy_conf_value(key, base_dir=None):
    """读取 deploy.conf 中某键的生效值（最后一条非注释行）；不存在返回 None。

    只读、无副作用，供管理端回显"已保存但待重启"的值。
    """
    path = _deploy_conf_path(base_dir)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return None
    value = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        k, v = stripped.split('=', 1)
        if k.strip().lower() == str(key).strip().lower():
            value = v.strip()
    return value


def update_deploy_conf_value(key, value, base_dir=None):
    """原子地把 key=value 写入 deploy.conf，保留既有注释与其余配置。

    管理端对部署参数（如 waitress_threads）的修改走这里：替换所有同名行
    （生效行或注释样例行），不存在则追加到末尾。键名/值做白名单校验，
    写入同目录临时文件后 os.replace，避免写到一半留下截断的配置文件。

    @return: 成功 True；参数非法或文件不可写 False。
    """
    key = str(key).strip()
    value = str(value).strip()
    if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
            or not value or '\n' in value or '\r' in value):
        return False
    path = _deploy_conf_path(base_dir)
    try:
        # newline='' 保留原行尾（Windows 安装生成的 deploy.conf 为 CRLF），
        # 避免管理端保存一次就把整份文件改写成 LF
        with open(path, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''
    except OSError:
        return False
    pattern = re.compile(
        r'^[ \t]*#?[ \t]*' + re.escape(key) + r'[ \t]*=[^\r\n]*',
        re.MULTILINE | re.IGNORECASE)
    if pattern.search(text):
        text = pattern.sub(f'{key}={value}', text)
    else:
        newline = '\r\n' if '\r\n' in text else '\n'
        if text and not text.endswith(('\n', '\r')):
            text += newline
        text += f'{key}={value}{newline}'
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix='.deploy-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            os.replace(tmp_path, path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        return False
    return True


def _deploy_pick(deploy_cfg, env_key, file_key, default):
    """部署参数取值：环境变量 > deploy.conf > 默认值。"""
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val
    return deploy_cfg.get(file_key, default)


def _deploy_int(deploy_cfg, env_key, file_key, default, minimum=1,
                maximum=None):
    """整型部署参数取值；非法/越界时告警并回退默认值。

    配置错误不应让应用在**导入期**崩溃（此前 int('abc') 直接
    ValueError，服务反复重启且日志只有一行无上下文的 traceback）。
    """
    raw = _deploy_pick(deploy_cfg, env_key, file_key, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logging.getLogger(__name__).warning(
            '配置项 %s=%r 不是整数，已回退默认值 %s', file_key, raw, default)
        return default
    if value < minimum:
        logging.getLogger(__name__).warning(
            '配置项 %s=%s 小于下限 %s，已回退默认值 %s',
            file_key, value, minimum, default)
        return default
    if maximum is not None and value > maximum:
        logging.getLogger(__name__).warning(
            '配置项 %s=%s 大于上限 %s，已回退默认值 %s',
            file_key, value, maximum, default)
        return default
    return value


# 旧版小写缓存后端名 → flask-caching 2.5+ 的类名。
# flask-caching 2.3 的 backends/__init__.py 里还有 simple()/filesystem() 这类
# 兼容垫片函数，2.5 起删除、只剩类名——此时 CACHE_TYPE='simple' 会在
# import_string('flask_caching.backends.simple') 处抛 ImportError，**应用启动
# 即崩**（本机实测：装机预置 flask-caching 2.5.1 + deploy.conf 的
# cache_type=simple，服务起来数秒后挂掉，日志只留一行 ImportError）。
# 存量部署的 deploy.conf 写的就是小写名，故统一换算而非要求用户改配置。
_CACHE_TYPE_ALIASES = {
    'simple': 'SimpleCache',
    'null': 'NullCache',
    'filesystem': 'FileSystemCache',
    'redis': 'RedisCache',
    'redissentinel': 'RedisSentinelCache',
    'rediscluster': 'RedisClusterCache',
    'memcached': 'MemcachedCache',
    'saslmemcached': 'SASLMemcachedCache',
    'spreadsaslmemcached': 'SpreadSASLMemcachedCache',
}


def _parse_host_allowlist(raw):
    """trusted_hosts 取值 → 主机名列表（去空白、去空项）。"""
    return [h.strip() for h in (raw or '').split(',') if h.strip()]


class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    SECRET_KEY = _load_or_create_secret_key(BASE_DIR)
    APP_VERSION = APP_VERSION
    APP_COPYRIGHT = APP_COPYRIGHT
    APP_LICENSE = APP_LICENSE

    # 部署调优参数统一入口：instance/deploy.conf（优先级：环境变量 > 文件 > 默认）
    _deploy = _load_deploy_settings(BASE_DIR)

    # Waitress 工作线程数（单进程并发能力），部署参数可调
    WAITRESS_THREADS = _deploy_int(
        _deploy, 'WAITRESS_THREADS', 'waitress_threads',
        WAITRESS_THREADS_DEFAULT, minimum=WAITRESS_THREADS_MIN,
        maximum=WAITRESS_THREADS_MAX)

    # PostgreSQL 连接（环境变量 > 安装向导 postgresql.txt > 内置默认）
    _db = _load_db_settings(BASE_DIR)
    DB_HOST = _db['host']
    DB_PORT = _db['port']
    DB_NAME = _db['name']
    DB_USER = _db['user']
    DB_PASS = _db['password']

    SQLALCHEMY_DATABASE_URI = (
        f'postgresql+psycopg2://{DB_USER}:{quote_plus(DB_PASS)}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    # 容量规划：目标 250 并发用户
    #   每个 Waitress 线程同一时刻最多占用 1 个数据库连接，连接池按
    #   waitress_threads 自动放大（48 线程 → 40 + 20 = 上限 60，保持原值）：
    #   pool_size = max(40, ceil(线程数×5/6))
    #   max_overflow = max(20, ceil(线程数×5/12))
    #   pool_recycle 1800s 防止 PostgreSQL idle 超时切断
    #   注意：PostgreSQL 默认 max_connections=100；调高线程数时需同步调高
    #   max_connections，并为管理员/备份连接留出余量（多实例时再核算）
    _db_pool_size = max(40, math.ceil(WAITRESS_THREADS * 5 / 6))
    _db_max_overflow = max(20, math.ceil(WAITRESS_THREADS * 5 / 12))
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': _db_pool_size,
        'max_overflow': _db_max_overflow,
        'pool_recycle': 1800,
        'pool_pre_ping': True,
        'pool_use_lifo': True,
    }

    # 上传文件配置
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'py'}
    # 全局请求体兜底上限 210MB：JSON 请求的 25MB 防护由 before_request
    # 钩子按 content_type 强制（get_json 全量读入内存的内存型 DoS 面；
    # 25MB 覆盖课堂页 PPTist 课件缓存保存）；
    # multipart 上传按角色限制（管理员不限、非管理员 200MB，同钩子），
    # 各端点自身的单文件上限（作业 50/100MB、网盘 200MB、活动 20MB 等）
    # 在解析层之上生效。大文件资源上传走分块接口（每 chunk 5MB 独立
    # 请求，不受单请求上限影响，50GB 级仍可完成）。
    MAX_CONTENT_LENGTH = 210 * 1024 * 1024   # 最大单一请求 210 MB
    NON_ADMIN_UPLOAD_LIMIT = 200 * 1024 * 1024   # 200 MB

    # 静态文件
    STATIC_FOLDER = 'static'
    STATIC_URL_PATH = '/static'

    # 管理员账号文件路径由 app.utils.get_admin_account_file() 统一解析
    # （默认项目根目录；容器部署用环境变量 ADMIN_ACCOUNT_FILE 指向持久卷）

    # 缓存配置
    # 生产为 Waitress 单进程部署：进程内 simple 缓存（读写亚毫秒级），
    # 消除 filesystem 缓存在 Windows 上的并发写锁问题（无文件锁，NTFS 并发
    # rename 指数退避最长阻塞 10s + 每次 set 全目录扫描）。多进程部署时
    # 切换 CACHE_TYPE=filesystem（deploy.conf 或环境变量）或接入 Redis。
    # CACHE_DIR 支持覆盖：测试脚本（独立测试库）通过设置 CACHE_DIR
    # 隔离缓存，避免 lookup:classes 等共享键被测试数据污染主库缓存命中
    CACHE_TYPE = _deploy_pick(_deploy, 'CACHE_TYPE', 'cache_type', 'SimpleCache') or 'SimpleCache'
    _cache_type_raw = CACHE_TYPE.strip()
    CACHE_TYPE = _CACHE_TYPE_ALIASES.get(_cache_type_raw.lower(), _cache_type_raw)
    _cache_dir_raw = (_deploy_pick(_deploy, 'CACHE_DIR', 'cache_dir', '')
                      or os.path.join(BASE_DIR, 'data', 'cache'))
    # 相对路径按项目根目录解析：Windows 服务模式下 CWD 是 System32，
    # 直接 makedirs('data/cache') 会写到系统目录或因无权限启动失败。
    # 绝对路径保持原样（容器/自定义挂载）。
    CACHE_DIR = (_cache_dir_raw if os.path.isabs(_cache_dir_raw)
                 else os.path.join(BASE_DIR, _cache_dir_raw))
    CACHE_DEFAULT_TIMEOUT = 300
    CACHE_THRESHOLD = 1000
    # mode 参数仅 FileSystemCache 后端支持；SimpleCache 传入会 TypeError
    CACHE_OPTIONS = {'mode': 0o600} if CACHE_TYPE == 'FileSystemCache' else {}

    # ── Session / Cookie 安全配置（deploy.conf 或环境变量启用）──
    # 在 HTTPS 反向代理后部署时设 COOKIE_SECURE=1；开发环境自动关闭避免无法登录
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = _deploy_pick(
        _deploy, 'COOKIE_SECURE', 'cookie_secure', '0') == '1'
    # 延长 session 寿命：默认 8 小时与教学日匹配
    PERMANENT_SESSION_LIFETIME = 8 * 3600
    # 防止反向代理后 Host 头伪造（校验在 app/__init__.py 的 _enforce_trusted_host）。
    # 部署键仍叫 trusted_hosts / TRUSTED_HOSTS，但**不能**落到 Flask 同名配置项：
    # Flask 3.1 起原生读 app.config['TRUSTED_HOSTS']，在路由匹配前校验 Host，
    # 失败存为 routing_exception、在 before_request 之后抛 400——应用为
    # /api/healthz 做的豁免因此失效（容器 HEALTHCHECK 走 127.0.0.1 → 恒 unhealthy），
    # 且条目不去空白，`a, b` 的写法会让 b 全站 400。
    _trusted_hosts_raw = _deploy_pick(
        _deploy, 'TRUSTED_HOSTS', 'trusted_hosts', '')
    HOST_ALLOWLIST = _parse_host_allowlist(_trusted_hosts_raw)
    TRUSTED_HOSTS = None
    # 仅在应用确实位于可信反向代理之后时启用；否则客户端可伪造 X-Forwarded-*。
    TRUST_PROXY_HEADERS = _deploy_pick(
        _deploy, 'TRUST_PROXY_HEADERS', 'trust_proxy_headers', '0') == '1'
    # 代理密钥（可选）：设置后仅对携带 X-Proxy-Secret 头且值匹配的请求应用
    # ProxyFix/采信 XFF，防内网直连应用端口伪造转发头（见 DEPLOY_CONF_TEMPLATE 注释）
    PROXY_SECRET = _deploy_pick(_deploy, 'PROXY_SECRET', 'proxy_secret', '')
    # 学生自定义 AI 地址默认禁止访问 RFC1918 私网；校内模型需显式列入白名单。
    _ai_hosts_raw = _deploy_pick(
        _deploy, 'STUDENT_AI_PRIVATE_HOSTS', 'student_ai_private_hosts', '')
    STUDENT_AI_PRIVATE_HOSTS = {
        item.strip().lower()
        for item in _ai_hosts_raw.split(',')
        if item.strip()
    }

    # 登录失败单出口 IP 全局上限（学生/教师横向枚举防护）。
    # 校级代理/大 NAT 场景可经 deploy.conf 调至 100-150 降低误锁
    LOGIN_IP_GLOBAL_MAX_FAILS = _deploy_int(
        _deploy, 'LOGIN_IP_GLOBAL_MAX_FAILS', 'login_ip_global_max_fails', 50)

    # AI 流式对话全进程并发上限（耗尽 Waitress 线程池的兜底闸门，见模板注释）
    AI_MAX_CONCURRENT_STREAMS = _deploy_int(
        _deploy, 'AI_MAX_CONCURRENT_STREAMS', 'ai_max_concurrent_streams', 16)

    # 逐题分析结果短缓存（秒）；0 关闭。成绩提交/删除时按资源失效
    QUIZ_ANALYSIS_CACHE_SECONDS = _deploy_int(
        _deploy, 'QUIZ_ANALYSIS_CACHE_SECONDS', 'quiz_analysis_cache_seconds', 45)

    # 大文件附件下载专用线程池：并发名额与启用阈值（MB）；0 关闭
    LARGE_DOWNLOAD_POOL_SIZE = _deploy_int(
        _deploy, 'LARGE_DOWNLOAD_POOL_SIZE', 'large_download_pool_size', 8)
    LARGE_DOWNLOAD_THRESHOLD_MB = _deploy_int(
        _deploy, 'LARGE_DOWNLOAD_THRESHOLD_MB', 'large_download_threshold_mb', 16)

    # study_resources 示例数据
    STUDY_RESOURCES = [
        {"title": "Python基础教程", "url": "https://docs.python.org/zh-cn/3/tutorial/"},
        {"title": "Flask官方文档", "url": "https://flask.palletsprojects.com/zh-cn/latest/"},
        {"title": "Bootstrap中文文档", "url": "https://www.bootcss.com/"}
    ]
