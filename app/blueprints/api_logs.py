"""由 API 门面模块加载的领域路由。"""

from flask import current_app, jsonify

from app.extensions import db
from app.models import (
    Log,
)
from app.decorators import admin_login_required
from app.services.log_service import add_log
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Logs
# ──────────────────────────────────────────────


@api_bp.route('/logs', methods=['GET'])
@admin_login_required
def get_logs():
    """操作日志列表"""
    logs = Log.query.order_by(Log.time.desc()).limit(200).all()
    data = []
    for log in logs:
        data.append({
            'id': log.id,
            'user_id': log.user_id,
            'user_type': log.user_type,
            'action': log.action,
            'detail': log.detail,
            'time': log.time.strftime('%Y-%m-%d %H:%M:%S') if log.time else None
        })
    return jsonify({'success': True, 'data': data, 'message': 'ok'})


@api_bp.route('/logs/clear', methods=['POST'])
@admin_login_required
def clear_logs():
    """清除日志"""
    try:
        db.session.query(Log).delete()
        db.session.commit()
        # 记录清除操作
        add_log(user_id=0, user_type='admin',
                action='清除日志',
                detail='管理员清除了所有操作日志')
        db.session.commit()
        return jsonify({'success': True, 'message': '操作日志已清除'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 清除日志失败: {str(e)}")
        return jsonify({'success': False, 'message': '清除日志失败'}), 500

