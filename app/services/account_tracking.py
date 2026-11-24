# -*- coding: utf-8 -*-
"""账号登录会话与页面轨迹记录。

设计要点：
- 每次登录生成独立 session id，放 Flask 会话；同账号多终端各占一行。
- 正常退出/服务端清理写 logout_at；浏览器直接关闭保留 last_seen_at。
- 页面轨迹只记录顶层 HTML GET，不记录静态资源/API/iframe，不保存查询串。
- 所有写库均为 best-effort，失败只记日志，不影响业务请求。
"""
import uuid
from datetime import datetime, timedelta

from flask import current_app, request, session

from app.extensions import cache, db
from app.models import AccountPageView, AccountSession

_TOUCH_CACHE_PREFIX = 'account_session:touch:'
_PAGE_VIEW_SKIP_PREFIXES = ('/static/', '/api/', '/favicon.ico')
_SENSITIVE_ENDPOINTS = {
    'resources.courseware_view',
    'resources.courseware_frame',
    'resources.lesson_item_content',
}
_MAX_PATH = 500


def _client_ip():
    try:
        from app.utils import get_client_ip
        return (get_client_ip() or '')[:64]
    except Exception:
        return (request.remote_addr or '')[:64]


def _user_agent():
    try:
        return (request.user_agent.string or '')[:500]
    except Exception:
        return ''


def _end_session_id(session_id, reason):
    if not session_id:
        return
    try:
        row = db.session.get(AccountSession, session_id)
        if row is not None and row.logout_at is None:
            row.logout_at = datetime.now()
            row.logout_reason = (reason or 'logout')[:32]
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.debug('账号会话结束记录失败', exc_info=True)


def end_account_session(reason='logout'):
    """结束当前浏览器会话对应的登录会话（不影响同账号其他终端）。"""
    session_id = session.pop('account_session_id', None)
    _end_session_id(session_id, reason)


def start_account_session(account_type, account_id, account_name,
                          channel='web'):
    """登录成功后新建一个终端会话。返回 session id（失败返回 None）。"""
    session_id = uuid.uuid4().hex
    now = datetime.now()
    try:
        db.session.add(AccountSession(
            id=session_id, account_type=account_type, account_id=account_id,
            account_name=(account_name or '')[:80], channel=channel,
            login_at=now, login_ip=_client_ip(),
            user_agent=_user_agent(), last_seen_at=now, page_count=0))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.debug('账号会话开始记录失败', exc_info=True)
        return None
    session['account_session_id'] = session_id
    return session_id


def touch_account_session():
    """更新最后活跃时间；按会话 60 秒节流，避免每请求写库。"""
    session_id = session.get('account_session_id')
    if not session_id:
        return
    if request.path.startswith('/static/'):
        return
    key = _TOUCH_CACHE_PREFIX + session_id
    if cache.get(key):
        return
    try:
        row = db.session.get(AccountSession, session_id)
        if row is None:
            session.pop('account_session_id', None)
            return
        if row.logout_at is not None:
            session.pop('account_session_id', None)
            return
        row.last_seen_at = datetime.now()
        db.session.commit()
        cache.set(key, 1, timeout=60)
    except Exception:
        db.session.rollback()
        current_app.logger.debug('账号最后活跃更新失败', exc_info=True)


def record_page_view():
    """记录一次顶层 HTML 页面访问；iframe/静态/API 不计入。"""
    if request.method != 'GET':
        return
    path = request.path or ''
    if path.startswith(_PAGE_VIEW_SKIP_PREFIXES):
        return
    dest = (request.headers.get('Sec-Fetch-Dest') or '').lower()
    if dest and dest != 'document':
        return
    session_id = session.get('account_session_id')
    if not session_id:
        return
    endpoint = request.endpoint or ''
    if endpoint in _SENSITIVE_ENDPOINTS:
        return
    try:
        row = db.session.get(AccountSession, session_id)
        if row is None or row.logout_at is not None:
            return
        now = datetime.now()
        db.session.add(AccountPageView(
            session_id=session_id, account_type=row.account_type,
            account_id=row.account_id, endpoint=endpoint[:120],
            path=path[:_MAX_PATH], created_at=now))
        row.page_count = (row.page_count or 0) + 1
        row.last_seen_at = now
        db.session.commit()
        cache.set(_TOUCH_CACHE_PREFIX + session_id, 1, timeout=60)
    except Exception:
        db.session.rollback()
        current_app.logger.debug('账号页面轨迹记录失败', exc_info=True)


def cleanup_old_account_tracking(days=90):
    """清理超过保留期的会话/页面轨迹；按天节流，失败不影响页面。"""
    key = 'account_tracking:cleanup:last'
    if cache.get(key):
        return
    try:
        cache.set(key, 1, timeout=24 * 3600)
        cutoff = datetime.now() - timedelta(days=max(1, int(days)))
        old_ids = [sid for (sid,) in db.session.query(
            AccountSession.id).filter(
                AccountSession.login_at < cutoff).limit(2000).all()]
        if not old_ids:
            return
        AccountPageView.query.filter(
            AccountPageView.session_id.in_(old_ids)).delete(
                synchronize_session=False)
        AccountSession.query.filter(
            AccountSession.id.in_(old_ids)).delete(
                synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.debug('账号轨迹清理失败', exc_info=True)
