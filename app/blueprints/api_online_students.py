"""由 API 门面模块加载的领域路由。"""
from datetime import datetime, timedelta

from flask import current_app, jsonify
from sqlalchemy import func, or_

from app.extensions import cache, db
from app.models import (
    Student,
)
from app.decorators import admin_login_required
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Students
# ──────────────────────────────────────────────


@api_bp.route('/students/online', methods=['GET'])
@admin_login_required
def get_online_students():
    """在线学生列表"""
    cache_key = 'api:students:online'
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)
    thirty_mins_ago = datetime.now() - timedelta(minutes=30)
    # OR 结构会使 idx_student_last_seen 索引失效导致全表扫描；
    # UNION ALL 两个可走索引的分支，语义等价
    q1 = Student.query.filter(Student.last_seen >= thirty_mins_ago)
    q2 = Student.query.filter(
        Student.last_seen.is_(None) & (Student.login_time >= thirty_mins_ago))
    students = q1.union_all(q2).order_by(
        func.coalesce(Student.last_seen, Student.login_time).desc()).all()

    data = []
    for s in students:
        data.append({
            'id': s.id,
            'name': s.name,
            'class': s.student_class,
            'ip_address': s.ip_address,
            'login_time': s.login_time.strftime('%Y-%m-%d %H:%M:%S') if s.login_time else None,
            'last_seen': s.last_seen.strftime('%Y-%m-%d %H:%M:%S') if s.last_seen else None
        })
    result = {
        'success': True,
        'data': {
            'total': len(data),
            'students': data
        },
        'message': 'ok'
    }
    cache.set(cache_key, result, timeout=30)
    return jsonify(result)


@api_bp.route('/students/clear', methods=['POST'])
@admin_login_required
def clear_online_students():
    """清除在线学生"""
    try:
        thirty_mins_ago = datetime.now() - timedelta(minutes=30)
        online_filter = or_(
            Student.last_seen >= thirty_mins_ago,
            (Student.last_seen.is_(None) & (Student.login_time >= thirty_mins_ago))
        )
        one_year_ago = datetime.now() - timedelta(days=365)
        # 单条 UPDATE 替代全列加载后逐行赋值（此前 250 人在线 = 250 行
        # 全列传输 + 逐行 ORM flush）
        count_before = Student.query.filter(online_filter).update(
            {'login_time': one_year_ago, 'last_seen': one_year_ago},
            synchronize_session=False)
        db.session.commit()
        # 失效在线列表缓存（30s TTL），清除后管理端立即不再显示"幽灵在线"
        try:
            from app.extensions import cache as _oc_cache
            _oc_cache.delete('api:students:online')
        except Exception:
            pass
        current_app.logger.info(f"API 清除在线学生成功: 共 {count_before} 名")
        return jsonify({
            'success': True,
            'data': {'cleared_count': count_before},
            'message': f'已清除 {count_before} 名在线学生'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 清除在线学生失败: {str(e)}")
        return jsonify({'success': False, 'message': '清除失败'}), 500

