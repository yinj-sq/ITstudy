"""操作日志服务 — 统一的日志记录入口

提供 add_log() 函数，同时写入数据库和 Python logger。
推荐所有蓝图使用此函数替代手动创建 Log 对象。
"""
from datetime import datetime
import logging
from app.extensions import db
from app.models import Log

logger = logging.getLogger(__name__)


def add_log(user_id=0, user_type='admin', action='', detail=''):
    """添加一条操作日志（写入 DB + Python logger）

    不 commit — 由调用方在合适时机统一提交事务。

    Args:
        user_id: 操作人ID（0 表示系统/管理员）
        user_type: 用户类型 ('admin' / 'student')
        action: 操作描述
        detail: 详细内容

    Returns:
        Log 对象（已 add 到 session）
    """
    log_entry = Log(
        user_id=user_id,
        user_type=user_type,
        action=action,
        detail=detail,
        time=datetime.now()
    )
    db.session.add(log_entry)

    # 同时写入 Python logger，便于集中检索
    logger.info('[%s][uid=%s] %s | %s', user_type, user_id, action, detail)
    return log_entry
