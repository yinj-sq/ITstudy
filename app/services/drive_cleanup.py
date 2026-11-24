"""网盘自动清理后台线程。

在 create_app 启动时以 daemon 线程方式运行：按配置的检查周期醒来，
读取 SystemConfig 开关（drive_cleanup_enabled / idle_days / interval_hours），
启用时删除闲置 N 天未活动的个人网盘文件并记录操作日志。

- daemon 线程随应用进程退出，不阻塞关闭
- 每次醒来重读配置，修改界面配置后无需重启
- 互斥双保险：进程内 threading.Lock（同进程 _run_once 不并发）；
  跨实例锁文件独占创建（写 PID）+ 过期接管（1 小时/PID 失活），
  见 _try_acquire_lock / _lock_is_stale
"""
import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_worker_thread = None
_worker_started = False

# 进程内互斥：同一进程内 _run_once 不并发执行
_run_lock = threading.Lock()

# 跨进程锁文件过期时间（秒）：超过视为孤儿锁可接管
_LOCK_STALE_SECONDS = 3600


def _pid_alive(pid):
    """探测 PID 是否存活。

    Windows 下 os.kill(pid, 0) 会直接终止目标进程（TerminateProcess），
    不可用于探测，改用 tasklist 过滤；tasklist 失败时保守视为存活（不接管）。
    """
    if os.name == 'nt':
        try:
            out = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}'],
                capture_output=True, text=True, timeout=5)
            return str(pid) in (out.stdout or '')
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _lock_is_stale(lock_path):
    """锁文件是否可接管：存在超过 1 小时，或写入的 PID 已不存活。"""
    try:
        with open(lock_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except OSError:
        return True
    try:
        if time.time() - os.path.getmtime(lock_path) > _LOCK_STALE_SECONDS:
            return True
    except OSError:
        return True
    pid_str = content.split('\n', 1)[0] if content else ''
    if pid_str.isdigit():
        return not _pid_alive(int(pid_str))
    return True  # 无有效 PID → 视为过期


def _try_acquire_lock(app, lock_name='drive_cleanup.lock'):
    """跨实例执行互斥：独占创建锁文件（写 PID）。

    - 锁文件不存在 → 独占创建成功，写入 PID，持有锁
    - 锁文件存在且未过期、PID 存活 → 获取失败（本进程跳过本轮）
    - 锁文件过期或 PID 失活 → 删除旧锁后接管（孤儿锁自愈）

    lock_name 可指定不同锁文件（如 message_cleanup.lock），
    供其他后台清理任务复用本实现。

    Returns: (fd, lock_path)；fd 为已打开的锁文件句柄，获取失败返回 (None, None)。
    调用方须在 finally 中通过 _release_lock 释放。
    """
    lock_path = os.path.join(app.config.get('CACHE_DIR', 'data/cache'), lock_name)
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    except OSError:
        return None, None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _lock_is_stale(lock_path):
                return None, None
            try:
                os.remove(lock_path)
            except OSError:
                return None, None
            continue  # 旧锁已清理，重试独占创建
        except OSError:
            return None, None
        try:
            os.write(fd, f'{os.getpid()}\n'.encode('utf-8'))
            return fd, lock_path
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            return None, None


def _release_lock(lock_path, fd):
    """释放跨进程锁：关闭 fd 后删除锁文件。

    Windows 不允许删除被打开的文件，必须先 close；
    close 与 remove 之间的微小竞态由过期/PID 接管机制兜底。
    """
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.remove(lock_path)
    except OSError:
        pass


def _run_once(app):
    """执行一次清理（幂等；无文件或未启用时静默返回）。

    进程内 threading.Lock + 跨进程锁文件双重互斥，finally 中释放。
    """
    from app.services.student_drive_service import (
        get_cleanup_config, cleanup_idle_drive_files,
    )
    with _run_lock:
        lock_fd, lock_path = None, None
        try:
            lock_fd, lock_path = _try_acquire_lock(app)
            if lock_fd is None:
                logger.debug('网盘清理未获取跨进程锁，跳过本轮')
                return
            with app.app_context():
                cfg = get_cleanup_config()
                if not cfg['enabled']:
                    return
                result = cleanup_idle_drive_files(cfg['idle_days'])
                if result['deleted']:
                    logger.info('网盘自动清理完成: %s', result)
        finally:
            if lock_fd is not None:
                _release_lock(lock_path, lock_fd)
            # 清理线程绑定的 DB 会话：commit 抛异常（连接中断等）后会话进入
            # failed 状态，不销毁则下一轮任何查询抛 PendingRollbackError 并被
            # 吞掉 → 线程从此空转直到进程重启。remove 后下轮重建全新会话。
            try:
                from app.extensions import db as _db
                _db.session.remove()
            except Exception:
                pass


def _worker(app):
    """后台循环：醒来 → 检查开关 → 执行清理 → 继续休眠。"""
    from app.services.student_drive_service import get_cleanup_config
    while True:
        try:
            with app.app_context():
                cfg = get_cleanup_config()
                interval = max(1, cfg['interval_hours']) * 3600
        except Exception:
            interval = 24 * 3600
        time.sleep(interval)
        try:
            _run_once(app)
        except Exception:
            logger.exception('网盘自动清理执行异常（已忽略，下轮重试）')
            # 兜底：异常路径同样确保会话可重建，防 failed 状态累积
            try:
                from app.extensions import db as _db
                _db.session.remove()
            except Exception:
                pass


def start_drive_cleanup_worker(app):
    """启动网盘自动清理后台线程（幂等：重复调用不重复启动）。"""
    global _worker_thread, _worker_started
    if _worker_started:
        return
    _worker_started = True
    _worker_thread = threading.Thread(
        target=_worker, args=(app,), daemon=True,
        name='drive-cleanup-worker')
    _worker_thread.start()
    logger.info('网盘自动清理后台线程已启动（周期由界面配置控制）')
