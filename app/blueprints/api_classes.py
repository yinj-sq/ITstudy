"""由 API 门面模块加载的领域路由。"""

from flask import current_app, jsonify, request
from sqlalchemy import text

from app.extensions import db
from app.models import (
    Class, Student, StudyGroup, TeachingSession,
)
from app.decorators import admin_login_required
from app.utils import (
    get_classes_cached,
    invalidate_lookup_cache,
)
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Classes API
# ──────────────────────────────────────────────


@api_bp.route('/classes', methods=['GET'])
@admin_login_required
def api_get_classes():
    """获取班级列表"""
    classes = get_classes_cached()
    data = [{'id': c.id, 'name': c.name, 'description': c.description,
             'student_count': c.student_count, 'group_count': c.group_count,
             'create_time': c.create_time}
            for c in classes]
    return jsonify({'success': True, 'data': data, 'message': 'ok'})


@api_bp.route('/classes', methods=['POST'])
@admin_login_required
def api_create_class():
    """创建班级"""
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '班级名称不能为空'}), 400
    existing = Class.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'message': f'班级 "{name}" 已存在'}), 400
    cls = Class(name=name, description=data.get('description', '').strip())
    db.session.add(cls)
    db.session.commit()
    # GET /api/classes 走 get_classes_cached()（lookup:classes TTL 300s），
    # 写路径必须显式失效（HTML 版已做，API 版此前遗漏 → 列表最长 5 分钟陈旧）
    invalidate_lookup_cache('classes')
    return jsonify({'success': True, 'data': {'id': cls.id, 'name': cls.name}, 'message': '班级创建成功'})


@api_bp.route('/classes/<int:class_id>', methods=['PUT'])
@admin_login_required
def api_update_class(class_id):
    """编辑班级"""
    cls = db.get_or_404(Class, class_id)
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '班级名称不能为空'}), 400
    dup = Class.query.filter(Class.name == name, Class.id != class_id).first()
    if dup:
        return jsonify({'success': False, 'message': f'班级 "{name}" 已存在'}), 400
    from app.blueprints.class_management import propagate_class_rename
    old_name = cls.name
    cls.name = name
    cls.description = data.get('description', '').strip()
    propagate_class_rename(cls.id, old_name, name)
    db.session.commit()
    invalidate_lookup_cache('classes')
    return jsonify({'success': True, 'message': '班级更新成功'})


@api_bp.route('/classes/<int:class_id>', methods=['DELETE'])
@admin_login_required
def api_delete_class(class_id):
    """删除班级（与 Web 端 delete_class 的清理逻辑保持一致，先删子表再删主表）"""
    from app.models import (GroupFile, GroupJoinRequest, AttendanceRecord,
                            StudentDriveQuota, ClassroomSetting)
    cls = db.get_or_404(Class, class_id)
    if Student.query.filter_by(class_id=class_id).count() > 0:
        return jsonify({'success': False, 'message': '该班级下还有学生，请先移除'}), 400
    try:
        # 收集小组网盘磁盘文件路径（DB 提交成功后删除，与 HTML 版 delete_class 一致）
        group_disk_paths = []
        # 小组文件/加入申请 → 小组 → 签到记录 → 网盘容量覆盖 → 作业-班级关联
        group_ids = [g.id for g in StudyGroup.query.filter_by(class_id=class_id).all()]
        if group_ids:
            group_disk_paths = [gf.file_path for gf in GroupFile.query.filter(
                GroupFile.group_id.in_(group_ids)).all() if gf.file_path]
            GroupFile.query.filter(GroupFile.group_id.in_(group_ids)).delete(synchronize_session=False)
            GroupJoinRequest.query.filter(GroupJoinRequest.group_id.in_(group_ids)).delete(synchronize_session=False)
        StudyGroup.query.filter_by(class_id=class_id).delete()
        AttendanceRecord.query.filter(AttendanceRecord.class_id == class_id).delete(synchronize_session=False)
        StudentDriveQuota.query.filter(StudentDriveQuota.class_id == class_id).delete(synchronize_session=False)
        # 作业-班级多对多关联表（ORM 无级联，需手动清理）
        db.session.execute(text('DELETE FROM homework_classes WHERE class_id = :cid'), {'cid': class_id})
        # 解除 classroom_setting.active_class_id 对该班级的引用
        ClassroomSetting.query.filter_by(active_class_id=class_id).update(
            {ClassroomSetting.active_class_id: None}, synchronize_session=False)
        from app.models import ClassroomSession
        ClassroomSession.query.filter_by(class_id=class_id).delete(
            synchronize_session=False)
        TeachingSession.query.filter_by(class_id=class_id).update(
            {TeachingSession.class_id: None}, synchronize_session=False)
        db.session.delete(cls)
        db.session.commit()
        invalidate_lookup_cache('classes')
        # DB 提交成功后再删小组网盘磁盘文件（尽力而为，失败仅残留孤儿）
        if group_disk_paths:
            from app.utils import delete_file_from_disk as _delete_file
            for rel in group_disk_paths:
                try:
                    _delete_file(rel)
                except Exception:
                    pass
        return jsonify({'success': True, 'message': '班级已删除'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除班级失败: class_id={class_id}, error={e}", exc_info=True)
        return jsonify({'success': False, 'message': '删除班级失败'}), 500

