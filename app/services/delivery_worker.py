"""作业附件投递个人网盘 — 后台线程 + 进度上报。

教师发布/更新作业并勾选"投递到学生网盘"时，投递可能涉及数百名学生，
同步执行会长时间阻塞页面且无反馈。此处改为：
1. 调用方（homework.py）启动后台投递线程，进度写入缓存
   （key: hw_delivery:<homework_id>）
2. 前端作业列表页轮询进度接口，显示进度条与完成结果
   （含"容量不足未投递"学生名单的醒目提示）
3. 投递为容错模式：单个学生容量不足/失败不中断整体
"""
import logging
import threading
from datetime import datetime

from app.extensions import db

logger = logging.getLogger(__name__)

PROGRESS_PREFIX = 'hw_delivery:'

_delivery_threads = {}  # hw_id -> thread（防重复启动）
_delivery_start_lock = threading.Lock()  # 检查+启动的原子性（双击“发布”
# 两个请求可同时通过 is_alive 检查、各自启动线程 → 同一附件重复投递）
_delivery_rerun = {}  # hw_id -> (hw_dir, sender_name)：进行中又被触发时登记一次补跑
# 活跃投递集合（缓存键 hw_delivery:active）的读改写互斥：SimpleCache 下
# get 返回同一可变对象、append 原地生效掩盖了竞态；切换 FileSystemCache/
# Redis（deploy.conf 允许多进程部署）后并发的读-改-写会互相覆盖丢条目
_active_lock = threading.Lock()


def _progress_key(hw_id):
    return f'{PROGRESS_PREFIX}{hw_id}'


def start_homework_delivery(app, hw_id, hw_dir, sender_name='教师'):
    """启动作业附件投递后台线程（同一作业同时只跑一个线程）。

    进行中再次触发（如编辑作业时新增了附件）不能直接丢弃——此前直接
    return，页面却提示"正在补投递"，新增附件永远不会投递。改为登记一次
    补跑：本轮结束后自动再跑一遍（投递按作业+文件名幂等，已投的会跳过）。
    """
    from app.extensions import cache
    with _delivery_start_lock:
        running = _delivery_threads.get(hw_id)
        if running and running.is_alive():
            _delivery_rerun[hw_id] = (hw_dir, sender_name)
            logger.info('作业附件投递进行中，已登记本轮结束后补跑: hw_id=%s', hw_id)
            return
        # 进度重置只在真正启动时做：放在锁外会把进行中那一轮的计数清零
        cache.set(_progress_key(hw_id), {
            'status': 'running',
            'hw_id': hw_id,
            'total': 0,
            'done': 0,
            'delivered': 0,
            'insufficient': [],
            'failed': [],
            'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': None,
            'error': None,
        }, timeout=3600)
        t = threading.Thread(target=_delivery_worker,
                             args=(app, hw_id, hw_dir, sender_name),
                             daemon=True,
                             name=f'homework-delivery-{hw_id}')
        _delivery_threads[hw_id] = t
        t.start()
    logger.info('作业附件投递线程已启动: hw_id=%s', hw_id)


def _delivery_worker(app, hw_id, hw_dir, sender_name):
    """后台投递执行体：查询作业 → 容错投递 → 更新进度/结果。"""
    from app.extensions import cache
    from app.models import Homework
    from app.services.student_drive_service import deliver_homework_attachments
    key = _progress_key(hw_id)

    def _update(**fields):
        try:
            rec = cache.get(key) or {}
            rec.update(fields)
            cache.set(key, rec, timeout=3600)
        except Exception:
            logger.debug('投递进度更新失败（已忽略）', exc_info=True)

    def _progress(done, total):
        _update(done=done, total=total)

    try:
        with app.app_context():
            hw = db.session.get(Homework, hw_id)
            if not hw:
                _update(status='failed', error='作业不存在',
                        end_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                return
            result = deliver_homework_attachments(
                hw, hw_dir, sender_name=sender_name, progress=_progress)
        _update(status='done',
                done=result['total'],
                delivered=result['delivered'],
                insufficient=result['insufficient'],
                failed=result['failed'],
                end_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        logger.info('作业附件投递完成: hw_id=%s 成功=%s 容量不足=%s',
                    hw_id, result['delivered'], len(result['insufficient']))
    except Exception as exc:
        logger.exception('作业附件投递异常: hw_id=%s', hw_id)
        _update(status='failed', error=str(exc),
                end_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    finally:
        # 线程完成/失败后移除引用（仅当条目仍指向本线程时，避免与
        # 新启动线程的覆盖竞态），防止 dict 无界增长并允许重新投递
        with _delivery_start_lock:
            if _delivery_threads.get(hw_id) is threading.current_thread():
                _delivery_threads.pop(hw_id, None)
            rerun = _delivery_rerun.pop(hw_id, None)
        if rerun:
            start_homework_delivery(app, hw_id, *rerun)


def get_delivery_progress(hw_id):
    """查询单个作业投递进度（无记录返回 None）。"""
    from app.extensions import cache
    return cache.get(_progress_key(hw_id))


def get_active_deliveries():
    """列出全部进行中的投递（供列表页轮询）。"""
    from app.extensions import cache
    try:
        # Flask-Caching filesystem 不提供按前缀扫描，采用常见做法：
        # 维护一个活跃键集合（写入时登记，完成时移除）
        active = list(cache.get('hw_delivery:active') or [])
        result = []
        changed = False
        for hw_id in list(active):
            rec = cache.get(_progress_key(hw_id))
            if not rec:
                continue
            if rec.get('status') == 'running':
                result.append(rec)
            else:
                # 已完成：从活跃集合移除（保留记录供详情查询 1 小时）
                try:
                    active.remove(hw_id)
                    changed = True
                except (ValueError, TypeError):
                    pass
        if changed:
            with _active_lock:
                cache.set('hw_delivery:active', active, timeout=3600)
        return result
    except Exception:
        logger.debug('获取进行中投递失败（已忽略）', exc_info=True)
        return []


def register_active(hw_id):
    """登记进行中的投递（幂等）。"""
    from app.extensions import cache
    try:
        with _active_lock:
            active = list(cache.get('hw_delivery:active') or [])
            if hw_id not in active:
                active.append(hw_id)
                cache.set('hw_delivery:active', active, timeout=3600)
    except Exception:
        pass
