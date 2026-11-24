"""AI 对话消息归档清理后台线程。

在 create_app 启动时以 daemon 线程方式运行：按配置的检查周期醒来，
读取 SystemConfig 开关（ai_message_cleanup_enabled / retention_days /
interval_hours），启用时删除 N 天前的 AI 对话消息并记录操作日志。

设计要点（与 drive_cleanup 一致）：
- daemon 线程随应用进程退出，不阻塞关闭
- 每次醒来重读配置，修改界面配置后无需重启
- 互斥双保险：进程内 threading.Lock + 跨实例锁文件独占创建
  （复用 drive_cleanup 的锁实现，使用独立锁文件避免互相阻塞）
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from app.extensions import db

logger = logging.getLogger(__name__)

_worker_thread = None
_worker_started = False

# 进程内互斥：同一进程内 _run_once 不并发执行
_run_lock = threading.Lock()


def get_cleanup_config():
    """读取清理配置（每次醒来重读，界面配置即时生效）。"""
    from app.models import SystemConfig

    def _get_int(key, default):
        try:
            return int(SystemConfig.get(key, str(default)) or default)
        except (TypeError, ValueError):
            return default

    return {
        'enabled': SystemConfig.get_bool('ai_message_cleanup_enabled', True),
        # 数值钳制：DB 值被脚本/手工改为 0 或负数时 cutoff=now 会删除
        # 全部 AI 消息（set 接口有校验，但直接改库不经过它）
        'retention_days': max(1, _get_int('ai_message_retention_days', 180)),
        'interval_hours': max(1, _get_int('ai_message_cleanup_interval_hours', 24)),
    }


def cleanup_old_messages(retention_days):
    """删除 N 天前的 AI 对话消息，返回删除条数（幂等）。"""
    from app.models import AIChatMessage, Log
    cutoff = datetime.now() - timedelta(days=retention_days)
    result = AIChatMessage.query.filter(
        AIChatMessage.created_at < cutoff
    ).delete(synchronize_session=False)
    if result:
        # 删除与写操作日志同一事务（此前分两次 commit，日志 commit 失败时
        # 删除已生效但无审计记录）
        db.session.add(Log(
            user_id=0, user_type='system',
            action='AI对话消息归档清理',
            detail=f'清理 {retention_days} 天前的消息 {result} 条',
            time=datetime.now(),
        ))
    db.session.commit()
    return result


def _run_once(app):
    """执行一次清理（幂等；未启用时静默返回）。"""
    from app.services.drive_cleanup import _try_acquire_lock, _release_lock
    with _run_lock:
        lock_fd, lock_path = None, None
        try:
            lock_fd, lock_path = _try_acquire_lock(
                app, lock_name='message_cleanup.lock')
            if lock_fd is None:
                logger.debug('消息清理未获取跨进程锁，跳过本轮')
                return
            with app.app_context():
                cfg = get_cleanup_config()
                if not cfg['enabled']:
                    return
                deleted = cleanup_old_messages(cfg['retention_days'])
                if deleted:
                    logger.info('AI消息归档清理完成: 删除 %s 条', deleted)
        finally:
            if lock_fd is not None:
                _release_lock(lock_path, lock_fd)
            # 清理线程绑定的 DB 会话：commit 抛异常后会话进入 failed 状态，
            # 不销毁则线程空转直到进程重启。remove 后下轮重建全新会话。
            try:
                from app.extensions import db as _db
                _db.session.remove()
            except Exception:
                pass


def _worker(app):
    """后台循环：醒来 → 检查开关 → 执行清理 → 继续休眠。

    首次延迟 10 分钟执行（避开应用启动高峰），之后按配置周期。
    """
    time.sleep(600)
    while True:
        try:
            _run_once(app)
        except Exception:
            logger.debug('AI消息清理执行异常（已忽略）', exc_info=True)
            # 兜底：异常路径同样确保会话可重建，防 failed 状态累积
            try:
                from app.extensions import db as _db
                _db.session.remove()
            except Exception:
                pass
        try:
            with app.app_context():
                cfg = get_cleanup_config()
                interval = max(1, cfg['interval_hours']) * 3600
        except Exception:
            interval = 24 * 3600  # 配置读取失败按 24h 周期
        time.sleep(interval)


def start_message_cleanup_worker(app):
    """启动消息清理后台线程（幂等：重复调用只启动一次）。"""
    global _worker_thread, _worker_started
    if _worker_started:
        return
    _worker_started = True
    _worker_thread = threading.Thread(
        target=_worker, args=(app,), daemon=True,
        name='message-cleanup-worker')
    _worker_thread.start()
    logger.info('AI消息归档清理后台线程已启动（周期由界面配置控制）')
