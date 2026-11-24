import os

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from app.config import (WAITRESS_THREADS_DEFAULT, WAITRESS_THREADS_MAX,
                        WAITRESS_THREADS_MIN, read_deploy_conf_value,
                        update_deploy_conf_value)
from app.extensions import db
from app.models import SystemConfig
from app.decorators import admin_login_required


system_settings_bp = Blueprint('system_settings', __name__, url_prefix='')


SYSTEM_SWITCHES = [
    ('student_access_enabled', '学生端访问', '关闭后学生登录、学习资源、作业、考试和网盘页面返回维护提示'),
    ('admin_remote_enabled', '远程管理员登录', '关闭后仅本机地址可以打开管理员登录接口'),
    ('class_buttons_enabled', '上课/下课按钮', '关闭后课堂资源仍可访问，但教师不能创建上课/下课记录'),
    ('courseware_public_enabled', '课件公开访问', '开启（默认）后未登录访客可浏览 /study 与课件文件；关闭后课件仅登录用户可见'),
]

# AI 流式并发管理端覆盖值的合法范围（与 ai.py 的 _global_stream_limit 一致）
_AI_STREAM_MIN = 1
_AI_STREAM_MAX = 64


@system_settings_bp.route('/admin/system', methods=['GET', 'POST'])
@admin_login_required
def admin_system_settings():
    if request.method == 'POST':
        raw_limit = (request.form.get('ai_max_concurrent_streams') or '').strip()
        stream_limit = None
        if raw_limit:
            try:
                stream_limit = int(raw_limit)
            except ValueError:
                flash('AI 流式并发上限必须是整数', 'danger')
                return redirect(url_for('system_settings.admin_system_settings'))
            if not _AI_STREAM_MIN <= stream_limit <= _AI_STREAM_MAX:
                flash(f'AI 流式并发上限需在 {_AI_STREAM_MIN}–{_AI_STREAM_MAX} 之间', 'danger')
                return redirect(url_for('system_settings.admin_system_settings'))
        # Waitress 线程数写入 deploy.conf（重启生效）。字段缺省时不动；
        # 留空恢复默认值
        raw_threads = request.form.get('waitress_threads')
        waitress_threads = None
        if raw_threads is not None:
            raw_threads = raw_threads.strip()
            if raw_threads:
                try:
                    waitress_threads = int(raw_threads)
                except ValueError:
                    flash('Waitress 工作线程数必须是整数', 'danger')
                    return redirect(url_for('system_settings.admin_system_settings'))
                if not (WAITRESS_THREADS_MIN <= waitress_threads
                        <= WAITRESS_THREADS_MAX):
                    flash(f'Waitress 工作线程数需在 '
                          f'{WAITRESS_THREADS_MIN}–{WAITRESS_THREADS_MAX} 之间',
                          'danger')
                    return redirect(url_for('system_settings.admin_system_settings'))
            else:
                waitress_threads = WAITRESS_THREADS_DEFAULT
        if waitress_threads is not None:
            base_dir = os.path.abspath(
                os.path.join(current_app.root_path, '..'))
            if not update_deploy_conf_value(
                    'waitress_threads', str(waitress_threads), base_dir):
                flash('Waitress 工作线程数保存失败：无法写入 instance/deploy.conf',
                      'danger')
                return redirect(url_for('system_settings.admin_system_settings'))
        # 校验通过后再落库；留空写入空串表示恢复部署默认
        for key, _, _ in SYSTEM_SWITCHES:
            SystemConfig.set(key, 'true' if request.form.get(key) == '1' else 'false')
        SystemConfig.set('ai_max_concurrent_streams',
                         '' if stream_limit is None else str(stream_limit))
        db.session.commit()
        message = '系统设置已保存'
        if waitress_threads is not None:
            message += '；Waitress 线程数将在重启 ITstudy 服务后生效'
        flash(message, 'success')
        return redirect(url_for('system_settings.admin_system_settings'))

    # 远程管理员登录默认关闭（仅本机 127.0.0.1 访问不受影响，
    # __init__.py 的 is_local 已放行），其余开关默认开启
    default_map = {'admin_remote_enabled': False}
    values = {key: SystemConfig.get_bool(key, default_map.get(key, True)) for key, _, _ in SYSTEM_SWITCHES}

    # AI 流式并发：管理端覆盖值（空 = 使用 deploy.conf / 环境变量默认）
    ai_stream_default = current_app.config.get('AI_MAX_CONCURRENT_STREAMS', 16)
    ai_stream_limit = SystemConfig.get('ai_max_concurrent_streams') or ''
    try:
        parsed_limit = int(ai_stream_limit) if ai_stream_limit else 0
    except (TypeError, ValueError):
        parsed_limit = 0
    # 与 ai.py 的 _global_stream_limit 同口径：越界值视为未覆盖
    ai_stream_effective = (parsed_limit
                           if _AI_STREAM_MIN <= parsed_limit <= _AI_STREAM_MAX
                           else ai_stream_default)

    # Waitress 线程数：运行值在进程启动时确定；保存值供回显/重启后生效
    waitress_running = int(current_app.config.get(
        'WAITRESS_THREADS', WAITRESS_THREADS_DEFAULT))
    waitress_env_override = os.environ.get('WAITRESS_THREADS') is not None
    waitress_saved = waitress_running
    saved_threads_raw = read_deploy_conf_value('waitress_threads')
    if saved_threads_raw:
        try:
            parsed_threads = int(saved_threads_raw)
        except ValueError:
            parsed_threads = 0
        if WAITRESS_THREADS_MIN <= parsed_threads <= WAITRESS_THREADS_MAX:
            waitress_saved = parsed_threads

    # 部署调优参数展示（只读：编辑 instance/deploy.conf 后重启生效）
    deploy_params = [
        ('WAITRESS_THREADS', 'Waitress 工作线程数',
         '单进程并发能力，范围 8-128；本页上方可修改（重启生效），'
         '连接池按此自动放大（deploy.conf: waitress_threads）'),
        ('CACHE_TYPE', '缓存后端',
         'SimpleCache（单进程默认）/ FileSystemCache（多进程部署）；旧写法 simple/filesystem 自动换算'),
        ('CACHE_DIR', '缓存目录',
         'FileSystemCache 后端时的缓存位置'),
        ('SESSION_COOKIE_SECURE', 'Cookie Secure',
         'HTTPS 反代部署时设 1（deploy.conf: cookie_secure=1）'),
        ('HOST_ALLOWLIST', 'Host 白名单',
         '逗号分隔、禁带端口，留空不校验（deploy.conf: trusted_hosts）'),
        ('TRUST_PROXY_HEADERS', '信任代理头',
         '反代部署设 1（deploy.conf: trust_proxy_headers=1）'),
        ('STUDENT_AI_PRIVATE_HOSTS', 'AI 私网白名单',
         '学生自定义 AI 允许的私网地址（deploy.conf）'),
        ('LOGIN_IP_GLOBAL_MAX_FAILS', '单 IP 登录失败上限',
         '大 NAT 出口可调至 100-150（deploy.conf: login_ip_global_max_fails）'),
        ('AI_MAX_CONCURRENT_STREAMS', 'AI 流式并发默认值',
         '本页上方可运行时覆盖（1-64，无需重启）；此处为部署默认（deploy.conf: ai_max_concurrent_streams）'),
        ('QUIZ_ANALYSIS_CACHE_SECONDS', '逐题分析缓存时长',
         '逐题分析结果短缓存秒数，0 关闭；成绩提交/删除时立即失效（deploy.conf: quiz_analysis_cache_seconds）'),
        ('LARGE_DOWNLOAD_POOL_SIZE', '大文件下载并发',
         '附件下载专用线程池并发数，0 关闭专用池（deploy.conf: large_download_pool_size）'),
        ('LARGE_DOWNLOAD_THRESHOLD_MB', '大文件下载阈值',
         '超过该大小的附件走专用下载池，单位 MB（deploy.conf: large_download_threshold_mb）'),
        ('PROXY_SECRET', '代理密钥',
         '与反代 X-Proxy-Secret 头一致；仅携带正确密钥的请求才采信 X-Forwarded-*（deploy.conf: proxy_secret）；此处仅显示是否已设置'),
    ]

    def _fmt(v):
        if isinstance(v, (list, tuple, set)):
            v = ', '.join(sorted(str(x) for x in v))
        return str(v) if v not in (None, '') else '（未设置）'

    deploy_values = [{
        'key': key,
        'display': display,
        # 代理密钥是敏感值：仅显示「已设置/未设置」，不回显明文
        'value': ('已设置' if current_app.config.get('PROXY_SECRET')
                  else '（未设置）') if key == 'PROXY_SECRET'
                 else _fmt(current_app.config.get(key)),
        'hint': hint,
    } for key, display, hint in deploy_params]
    deploy_conf_path = os.path.abspath(
        os.path.join(current_app.root_path, '..', 'instance', 'deploy.conf'))

    return render_template('admin_system_settings.html',
                           switches=SYSTEM_SWITCHES, values=values,
                           ai_stream_limit=ai_stream_limit,
                           ai_stream_default=ai_stream_default,
                           ai_stream_effective=ai_stream_effective,
                           waitress_threads_running=waitress_running,
                           waitress_threads_saved=waitress_saved,
                           waitress_threads_default=WAITRESS_THREADS_DEFAULT,
                           waitress_threads_min=WAITRESS_THREADS_MIN,
                           waitress_threads_max=WAITRESS_THREADS_MAX,
                           waitress_env_override=waitress_env_override,
                           deploy_params=deploy_values,
                           deploy_conf_path=deploy_conf_path)
