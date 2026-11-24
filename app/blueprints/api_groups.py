"""由 API 门面模块加载的领域路由。"""

import os

from flask import current_app, jsonify, request

from app.extensions import db
from app.models import (
    Student, StudyGroup, GroupFile, GroupJoinRequest,
)
from app.decorators import admin_login_required
from app.utils import (
    parse_int,
)
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Groups API
# ──────────────────────────────────────────────


@api_bp.route('/groups', methods=['GET'])
@admin_login_required
def api_get_groups():
    """获取小组列表"""
    class_id = request.args.get('class_id', '', type=str)
    query = StudyGroup.query
    if class_id:
        cid = parse_int(class_id)
        if cid is not None:
            query = query.filter_by(class_id=cid)
    # eager load leader + 批量加载成员，消除循环内逐组查询（N+1）
    from sqlalchemy.orm import joinedload
    groups = query.options(joinedload(StudyGroup.leader)).order_by(StudyGroup.name).all()
    gids = [g.id for g in groups]
    members_map = {}
    if gids:
        for m in Student.query.filter(Student.group_id.in_(gids)).all():
            members_map.setdefault(m.group_id, []).append(m)
    data = []
    for g in groups:
        members = members_map.get(g.id, [])
        data.append({
            'id': g.id, 'name': g.name, 'class_id': g.class_id,
            'leader': {'id': g.leader.id, 'name': g.leader.name,
                       'student_number': g.leader.student_number} if g.leader else None,
            'member_count': len(members),
            'members': [{'id': m.id, 'name': m.name, 'student_number': m.student_number}
                        for m in members]
        })
    return jsonify({'success': True, 'data': data, 'message': 'ok'})


def _parse_id_list(raw):
    """把请求中的 id 列表规范化为 int 列表，过滤非数字元素。

    非数字元素直接传给 SQLAlchemy 会让 psycopg2 抛 DataError → 500。
    """
    result = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, bool):
                continue
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
    return result


def _validate_leader(class_id, leader_id):
    """校验组长存在且属于同一班级；不通过返回错误消息，通过返回 None。"""
    if leader_id is None:
        return None
    leader = db.session.get(Student, leader_id)
    if leader is None:
        return '组长不存在'
    if leader.class_id != class_id:
        return '组长必须属于该小组所在班级'
    return None


@api_bp.route('/groups', methods=['POST'])
@admin_login_required
def api_create_group():
    """创建小组"""
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    class_id = parse_int(data.get('class_id'))
    if not name or not class_id:
        return jsonify({'success': False, 'message': '小组名称和班级不能为空'}), 400
    if StudyGroup.query.filter_by(name=name, class_id=class_id).first():
        return jsonify({'success': False, 'message': '该班级已存在同名小组'}), 400
    leader_id = parse_int(data.get('leader_id'))
    leader_err = _validate_leader(class_id, leader_id)
    if leader_err:
        return jsonify({'success': False, 'message': leader_err}), 400
    group = StudyGroup(name=name, class_id=class_id, leader_id=leader_id)
    db.session.add(group)
    # 组长自动加入小组（更新 leader.group_id），否则组长无法访问小组网盘、
    # 也不出现在成员列表中（与 api_set_group_members 的成员语义一致）
    if leader_id:
        leader = db.session.get(Student, leader_id)
        if leader:
            db.session.flush()  # 先获取 group.id
            leader.group_id = group.id
    db.session.commit()
    return jsonify({'success': True, 'data': {'id': group.id}, 'message': '小组创建成功'})


@api_bp.route('/groups/<int:group_id>', methods=['PUT'])
@admin_login_required
def api_update_group(group_id):
    """编辑小组"""
    group = db.get_or_404(StudyGroup, group_id)
    data = request.get_json(force=True, silent=True) or request.form
    if data.get('name'):
        dup = StudyGroup.query.filter(
            StudyGroup.name == data['name'],
            StudyGroup.class_id == group.class_id,
            StudyGroup.id != group_id
        ).first()
        if dup:
            return jsonify({'success': False, 'message': '该班级已存在同名小组'}), 400
        group.name = data['name']
    if 'leader_id' in data:
        leader_id = parse_int(data.get('leader_id'))
        leader_err = _validate_leader(group.class_id, leader_id)
        if leader_err:
            return jsonify({'success': False, 'message': leader_err}), 400
        # 组长变更：旧组长退出小组（若仍是本组组长位则置空），新组长自动加入
        old_leader_id = group.leader_id
        group.leader_id = leader_id
        if old_leader_id and old_leader_id != leader_id:
            old_leader = db.session.get(Student, old_leader_id)
            if old_leader and old_leader.group_id == group.id:
                old_leader.group_id = None
        if leader_id:
            new_leader = db.session.get(Student, leader_id)
            if new_leader:
                new_leader.group_id = group.id
    db.session.commit()
    return jsonify({'success': True, 'message': '小组更新成功'})


@api_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@admin_login_required
def api_delete_group(group_id):
    """删除小组（含磁盘文件清理，与 Web 版 delete_group 一致）"""
    group = db.get_or_404(StudyGroup, group_id)
    # 1. 先删除小组网盘磁盘文件（ORM 级联只删记录，此前磁盘孤儿残留）
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    group_files = GroupFile.query.filter_by(group_id=group_id).all()
    for gf in group_files:
        if upload_folder and gf.file_path:
            try:
                abs_path = os.path.normpath(os.path.join(upload_folder, gf.file_path))
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError:
                current_app.logger.warning(f'删除小组文件失败（忽略）: {gf.file_path}')
    # 加入/退出申请（FK 无级联，不清理会在 commit 时抛 IntegrityError
    # → 删除必 500，此前缺陷；Web 版 delete_group 已有清理，此处对齐）
    GroupJoinRequest.query.filter(
        GroupJoinRequest.group_id == group_id).delete(synchronize_session=False)
    Student.query.filter_by(group_id=group_id).update({'group_id': None})
    db.session.delete(group)
    db.session.commit()
    return jsonify({'success': True, 'message': '小组已删除'})


@api_bp.route('/groups/<int:group_id>/members', methods=['PUT'])
@admin_login_required
def api_set_group_members(group_id):
    """设置小组成员"""
    group = db.get_or_404(StudyGroup, group_id)
    data = request.get_json(force=True, silent=True) or {}
    member_ids = _parse_id_list(data.get('member_ids', []))
    # 组长必须始终是成员，否则组长无法访问小组网盘
    if group.leader_id and group.leader_id not in member_ids:
        member_ids.append(group.leader_id)
    # 成员必须属于小组所在班级（此前缺失校验，可混入其他班学生，
    # 使跨班学生通过 group_id 获得该小组网盘访问权限）
    if member_ids:
        valid_ids = [sid for (sid,) in Student.query.with_entities(
            Student.id).filter(
            Student.id.in_(member_ids),
            Student.class_id == group.class_id).all()]
        member_ids = valid_ids
    Student.query.filter_by(group_id=group_id).update({'group_id': None})
    if member_ids:
        Student.query.filter(Student.id.in_(member_ids)).update(
            {'group_id': group_id}, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True, 'message': f'已更新 {len(member_ids)} 名组员'})
