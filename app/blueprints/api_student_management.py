"""由 API 门面模块加载的领域路由。"""

from flask import current_app, jsonify, request

from app.extensions import db
from app.models import (
    Class, Student, StudyGroup,
)
from app.decorators import admin_login_required
from app.utils import (
    generate_numeric_password, invalidate_lookup_cache, paginate_query,
    parse_int, get_client_ip, student_login_clear_throttle,
)
from app.blueprints.api import (
    api_bp, _parse_bool,
)

# ──────────────────────────────────────────────
#  Students Management API
# ──────────────────────────────────────────────


@api_bp.route('/management/students', methods=['GET'])
@admin_login_required
def api_get_students():
    """获取学生列表（支持分页、筛选、排序）"""
    class_id = request.args.get('class_id', '', type=str)
    search = request.args.get('search', '', type=str)
    sort_by = request.args.get('sort', 'id')
    order = request.args.get('order', 'asc')

    query = Student.query
    if class_id:
        cid = parse_int(class_id)
        if cid is not None:
            query = query.filter_by(class_id=cid)
    if search:
        query = query.filter(db.or_(
            Student.name.contains(search),
            Student.student_number.contains(search),
            Student.student_class.contains(search)
        ))

    # 排序字段白名单校验，防止按 password_hash 等敏感字段排序导致信息泄露
    ALLOWED_SORT_FIELDS = {'id', 'name', 'student_number', 'student_class',
                           'class_id', 'group_id', 'is_activated', 'login_time'}
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = 'id'
    sort_col = getattr(Student, sort_by)
    query = query.order_by(sort_col.desc() if order == 'desc' else sort_col.asc())

    # eager load class_/group，消除分页列表内逐行 lazy 查询
    from sqlalchemy.orm import joinedload
    pagination = paginate_query(
        query.options(joinedload(Student.class_), joinedload(Student.group)))
    return jsonify({
        'success': True,
        'data': {
            'students': [{
                'id': s.id, 'name': s.name, 'student_number': s.student_number,
                'student_class': s.student_class, 'class_name': s.class_.name if s.class_ else None,
                'class_id': s.class_id, 'group_id': s.group_id,
                'group_name': s.group.name if s.group else None,
                'is_activated': s.is_activated,
                'has_changed_password': s.has_changed_password,
                'login_time': s.login_time.strftime('%Y-%m-%d %H:%M:%S') if s.login_time else None,
                'ip_address': s.ip_address
            } for s in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'page': pagination.page,
            'per_page': pagination.per_page
        },
        'message': 'ok'
    })


@api_bp.route('/management/students', methods=['POST'])
@admin_login_required
def api_create_student():
    """创建学生"""
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '姓名不能为空'}), 400
    student_number = data.get('student_number', '').strip()
    if student_number:
        if Student.query.filter_by(student_number=student_number).first():
            return jsonify({'success': False, 'message': f'学号 {student_number} 已存在'}), 400
    class_id = parse_int(data.get('class_id'))
    if class_id is not None and not db.session.get(Class, class_id):
        # 此前不校验班级存在性，非法 class_id 在 commit 时 FK IntegrityError → 500
        return jsonify({'success': False, 'message': '班级不存在'}), 400
    student = Student(
        name=name, student_number=student_number or None,
        student_class=str(data.get('student_class') or '').strip(),
        class_id=class_id,
        is_activated=_parse_bool(data.get('is_activated'), True)
    )
    supplied_password = data.get('password', '').strip()
    password = supplied_password or generate_numeric_password()
    if len(password) < 6:
        return jsonify({'success': False, 'message': '密码长度至少6位'}), 400
    student.set_password(password)
    db.session.add(student)
    db.session.commit()
    invalidate_lookup_cache('classes')
    response_data = {'id': student.id}
    if not supplied_password:
        response_data['initial_password'] = password
    return jsonify({'success': True, 'data': response_data, 'message': '学生创建成功'})


@api_bp.route('/management/students/<int:student_id>', methods=['PUT'])
@admin_login_required
def api_update_student(student_id):
    """编辑学生信息"""
    student = db.get_or_404(Student, student_id)
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '姓名不能为空'}), 400
    student_number = data.get('student_number', '').strip()
    if student_number and student_number != student.student_number:
        dup = Student.query.filter(
            Student.student_number == student_number,
            Student.id != student_id
        ).first()
        if dup:
            return jsonify({'success': False, 'message': f'学号 {student_number} 已存在'}), 400
    student.name = name
    # 空学号转 NULL（与 api_create_student / HTML edit_student 的 `or None`
    # 语义一致）：uq_student_number 唯一约束把多个空串视为同一值，
    # 多个学生清空学号时 commit 抛 IntegrityError → 500（此前缺陷）
    student.student_number = student_number or None
    student.student_class = str(data.get('student_class') or '').strip()
    new_class_id = parse_int(data.get('class_id'))
    new_group_id = parse_int(data.get('group_id'))
    # 班级/小组一致性校验（与 Web 版 edit_student 对齐）：
    # 小组必须属于学生所在班级，否则可造出"班级 A + 小组班级 B"的脏数据，
    # 使小组网盘/作业归属错乱
    if new_group_id:
        grp = db.session.get(StudyGroup, new_group_id)
        if not grp:
            return jsonify({'success': False, 'message': '小组不存在'}), 400
        if grp.class_id != new_class_id:
            return jsonify({'success': False, 'message': '小组必须属于学生所在班级'}), 400
    student.class_id = new_class_id
    student.group_id = new_group_id
    student.is_activated = _parse_bool(data.get('is_activated'), True)
    try:
        db.session.commit()
    except Exception as e:
        # 并发/脏数据导致的唯一约束等冲突：返回 JSON 错误而非 500
        db.session.rollback()
        current_app.logger.error(f"API 更新学生失败: student_id={student_id}, error={e}", exc_info=True)
        return jsonify({'success': False, 'message': '更新失败，请检查数据是否重复'}), 400
    invalidate_lookup_cache('classes')
    return jsonify({'success': True, 'message': '学生信息更新成功'})


@api_bp.route('/management/students/<int:student_id>', methods=['DELETE'])
@admin_login_required
def api_delete_student(student_id):
    """删除学生"""
    student = db.get_or_404(Student, student_id)
    try:
        # 先清理外键引用（与批量删除/class_management 一致），
        # 否则有考试结果等关联记录时删除触发 IntegrityError → 500
        from app.blueprints.class_management import _cleanup_student_records
        _cleanup_student_records(student_id)
        db.session.delete(student)
        db.session.commit()
        invalidate_lookup_cache('classes')
        return jsonify({'success': True, 'message': '学生已删除'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'API 删除学生 {student_id} 失败: {e}', exc_info=True)
        return jsonify({'success': False, 'message': '删除失败，请重试'}), 500


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


@api_bp.route('/management/students/batch-delete', methods=['POST'])
@admin_login_required
def api_batch_delete_students():
    """批量删除学生"""
    data = request.get_json(force=True, silent=True) or {}
    ids = _parse_id_list(data.get('ids', []))
    if not ids:
        return jsonify({'success': False, 'message': '请选择要删除的学生'}), 400
    try:
        # 先清理外键引用（与 class_management 删除单个学生一致），
        # 否则有考试结果等关联记录时 bulk delete 触发 IntegrityError → 500；
        # 按 id 集合一次性清理，避免逐人循环 14 次 DB 往返
        from app.blueprints.class_management import _cleanup_student_records_batch
        _cleanup_student_records_batch(ids)
        deleted = Student.query.filter(Student.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        invalidate_lookup_cache('classes')
        return jsonify({'success': True, 'message': f'已删除 {deleted} 名学生'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'API 批量删除学生失败: {e}', exc_info=True)
        return jsonify({'success': False, 'message': '批量删除失败，请重试'}), 500


@api_bp.route('/management/students/<int:student_id>/reset-password', methods=['POST'])
@admin_login_required
def api_reset_student_password(student_id):
    """重置学生密码"""
    student = db.get_or_404(Student, student_id)
    data = request.get_json(force=True, silent=True) or {}
    new_pw = data.get('new_password', '').strip()
    if len(new_pw) < 6:
        return jsonify({'success': False, 'message': '密码长度至少6位'}), 400
    if len(new_pw) > 50:
        return jsonify({'success': False, 'message': '密码长度不能超过50位'}), 400
    student.set_password(new_pw)
    student.has_changed_password = False
    db.session.commit()
    # 重置密码即解除登录封锁（学号/姓名维度 + 最近 IP），可立即重新登录
    student_login_clear_throttle(
        student.student_number, student.name,
        [student.ip_address, get_client_ip()])
    return jsonify({'success': True, 'message': '密码已重置'})


@api_bp.route('/management/students/batch-reset-password', methods=['POST'])
@admin_login_required
def api_batch_reset_password():
    """批量重置密码"""
    data = request.get_json(force=True, silent=True) or {}
    ids = _parse_id_list(data.get('ids', []))
    new_pw = data.get('new_password', '').strip()
    if not ids:
        return jsonify({'success': False, 'message': '请选择学生'}), 400
    if len(new_pw) < 6:
        return jsonify({'success': False, 'message': '密码长度至少6位'}), 400
    if len(new_pw) > 50:
        return jsonify({'success': False, 'message': '密码长度不能超过50位'}), 400
    count = 0
    reset_students = []
    for sid in ids:
        student = db.session.get(Student, sid)
        if student:
            student.set_password(new_pw)
            student.has_changed_password = False
            reset_students.append(
                (student.student_number, student.name, student.ip_address))
            count += 1
    db.session.commit()
    admin_ip = get_client_ip()
    for number, name, last_ip in reset_students:
        student_login_clear_throttle(number, name, [last_ip, admin_ip])
    return jsonify({'success': True, 'message': f'已重置 {count} 名学生密码'})


@api_bp.route('/management/students/import', methods=['POST'])
@admin_login_required
def api_import_students():
    """批量导入学生"""
    data = request.get_json(force=True, silent=True) or {}
    # 显式转为 int：非数字字符串传给 Class.query.get 会抛 psycopg2 DataError → 500
    class_id = parse_int(data.get('class_id'))
    students_data = data.get('students', [])

    if not class_id:
        return jsonify({'success': False, 'message': '请选择目标班级'}), 400
    if not students_data:
        return jsonify({'success': False, 'message': '请提供学生数据'}), 400

    cls = db.session.get(Class, class_id)
    if not cls:
        return jsonify({'success': False, 'message': '班级不存在'}), 404

    imported, skipped = 0, 0
    batch_password = (data.get('default_password') or '').strip() or generate_numeric_password()
    if len(batch_password) < 6:
        return jsonify({'success': False, 'message': '批量初始密码长度至少6位'}), 400

    # 性能优化：预加载现有学号（一次查询替代逐行 filter_by 查重）
    existing_numbers = {
        r[0] for r in db.session.query(Student.student_number).all() if r[0]
    }
    pending = []  # (name, number, password)
    if not isinstance(students_data, list):
        return jsonify({'success': False, 'message': '学生数据格式无效'}), 400
    for stu in students_data:
        # 逐项类型兜底：非 dict / 非字符串 / 超长字段此前直接 500
        if not isinstance(stu, dict):
            skipped += 1
            continue
        name = str(stu.get('name') or '').strip()
        number = str(stu.get('student_number') or '').strip()
        if not name or not number or len(name) > 50 or len(number) > 50:
            skipped += 1
            continue
        # 重复检测：学号全局唯一（跨班重复学号会导致登录命中他人账号，
        # 且登录已按上课班级过滤后本班学生将被阻断登录）
        if number in existing_numbers:
            skipped += 1
            continue
        student_password = str(stu.get('password') or '').strip() or batch_password
        if len(student_password) < 6:
            skipped += 1
            continue
        pending.append((name, number, student_password))
        existing_numbers.add(number)
        imported += 1

    # 批量密码哈希：pbkdf2 为慢哈希，多线程并行（hashlib 实现释放 GIL），
    # 342 名学生独立密码从数分钟降到数十秒
    from concurrent.futures import ThreadPoolExecutor
    from werkzeug.security import generate_password_hash as _gph
    if pending:
        with ThreadPoolExecutor(max_workers=8) as ex:
            hashes = list(ex.map(lambda p: _gph(p, method='pbkdf2:sha256'),
                                 [p[2] for p in pending]))
        new_students = [
            Student(name=p[0], student_number=p[1], class_id=class_id,
                    password_hash=h)
            for p, h in zip(pending, hashes)
        ]
        db.session.add_all(new_students)
    db.session.commit()
    invalidate_lookup_cache('classes')
    return jsonify({
        'success': True,
        'data': {'imported': imported, 'skipped': skipped,
                 'default_initial_password': batch_password},
        'message': f'成功导入 {imported} 名，跳过 {skipped} 名'
    })
