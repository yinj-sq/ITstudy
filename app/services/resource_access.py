# -*- coding: utf-8 -*-
"""教师资源访问权限的统一判断。

规则（与产品约定一致）：
- 管理员：全部资源可读可写。
- 教师创建者：own，读写全权限。
- resource_share 中的教师：shared，只读，可在课堂使用。
- 其他教师：不可见。
- 编辑模式只能看到自己的资源；只读模式可见自己的 + 被共享的资源。
"""
from sqlalchemy import and_, or_

from app.extensions import db
from app.models import (Resource, Subject, Class, TeachingSession, Teacher,
                        resource_audience, resource_share, teacher_subject,
                        teacher_class)


def teacher_class_ids(teacher_id):
    if not teacher_id:
        return set()
    rows = db.session.execute(
        teacher_class.select().where(teacher_class.c.teacher_id == teacher_id)
    ).fetchall()
    return {row.class_id for row in rows}


def teacher_classes(teacher_id):
    if not teacher_id:
        return []
    return (Class.query.join(
        teacher_class, teacher_class.c.class_id == Class.id
    ).filter(teacher_class.c.teacher_id == teacher_id)
      .order_by(Class.name).all())


def teacher_subject_ids(teacher_id):
    if not teacher_id:
        return set()
    rows = db.session.execute(
        teacher_subject.select().where(teacher_subject.c.teacher_id == teacher_id)
    ).fetchall()
    return {row.subject_id for row in rows}


def teacher_subjects(teacher_id):
    if not teacher_id:
        return []
    return (Subject.query.join(
        teacher_subject, teacher_subject.c.subject_id == Subject.id
    ).filter(teacher_subject.c.teacher_id == teacher_id)
      .order_by(Subject.sort_order, Subject.name).all())


def teacher_subject_allowed(teacher_id, subject_id):
    if not teacher_id or not subject_id:
        return False
    return db.session.execute(
        teacher_subject.select().where(
            teacher_subject.c.teacher_id == teacher_id,
            teacher_subject.c.subject_id == subject_id)
    ).first() is not None


def resource_access_level(resource, teacher_id, is_admin=False):
    if not resource:
        return 'none'
    if is_admin:
        return 'admin'
    if not teacher_id:
        return 'none'
    if resource.creator_teacher_id == teacher_id:
        return 'owner'
    # 已通过 selectin 预加载 shared_teachers 时避免逐资源查询
    # （教师资源库一页几十个资源 = 几十次 SQL）
    if 'shared_teachers' in resource.__dict__:
        shared = any(t.id == teacher_id
                     for t in (resource.shared_teachers or []))
    else:
        shared = db.session.execute(
            resource_share.select().where(
                resource_share.c.resource_id == resource.id,
                resource_share.c.teacher_id == teacher_id)
        ).first() is not None
    return 'shared' if shared else 'none'


def teacher_can_view(resource, teacher_id, is_admin=False, mode='readonly'):
    level = resource_access_level(resource, teacher_id, is_admin)
    if level == 'admin' or level == 'owner':
        return True
    if level == 'shared' and mode != 'edit':
        return True
    return False


def teacher_can_edit(resource, teacher_id, is_admin=False):
    return resource_access_level(resource, teacher_id, is_admin) in ('admin', 'owner')


def teacher_audience_condition(teacher_id):
    """该教师命中的授权资源 id 子查询（交集+通配语义）。

    教师须同时满足：年级 ∈ 授权行年级（行 grade 为 NULL 表示不限）且
    任教学科 ∈ 授权行学科（行 subject_id 为 NULL 表示不限）。教师未维护
    年级/学科时只有通配行命中（显式授权 fail-closed）。
    """
    teacher = db.session.get(Teacher, teacher_id) if teacher_id else None
    grade = (teacher.grade or '').strip() if teacher else ''
    subject_ids = teacher_subject_ids(teacher_id)
    grade_ok = resource_audience.c.grade.is_(None)
    if grade:
        grade_ok = or_(grade_ok, resource_audience.c.grade == grade)
    subject_ok = resource_audience.c.subject_id.is_(None)
    if subject_ids:
        subject_ok = or_(subject_ok,
                         resource_audience.c.subject_id.in_(subject_ids))
    return db.session.query(resource_audience.c.resource_id).filter(
        grade_ok, subject_ok)


def _legacy_public_condition():
    """旧 is_public 语义仅在资源没有任何授权记录时生效（授权记录优先）。"""
    has_audience = db.session.query(resource_audience.c.id).filter(
        resource_audience.c.resource_id == Resource.id).exists()
    return and_(Resource.is_public.is_(True), ~has_audience)


def teacher_can_use_resource(resource, teacher_id):
    """教师课堂可用性（只读使用）：授权记录优先，无记录回退 is_public。

    管理员/资源创建者的编辑权限仍由 teacher_can_edit 单独判断。
    """
    if not resource or not teacher_id:
        return False
    rows = db.session.execute(
        resource_audience.select().where(
            resource_audience.c.resource_id == resource.id)).fetchall()
    if not rows:
        return bool(resource.is_public)
    teacher = db.session.get(Teacher, teacher_id)
    grade = (teacher.grade or '').strip() if teacher else ''
    subject_ids = teacher_subject_ids(teacher_id)
    for row in rows:
        if row.grade and row.grade != grade:
            continue
        if row.subject_id and row.subject_id not in subject_ids:
            continue
        return True
    return False


def teacher_visible_resources(teacher_id, is_admin=False, mode='readonly',
                              classroom=False):
    query = Resource.query
    if not is_admin:
        if not teacher_id:
            return query.filter(db.false())
        if mode == 'edit':
            base = Resource.creator_teacher_id == teacher_id
        else:
            shared_ids = db.session.query(resource_share.c.resource_id).filter(
                resource_share.c.teacher_id == teacher_id)
            base = or_(
                Resource.creator_teacher_id == teacher_id,
                Resource.id.in_(shared_ids))
        if classroom:
            # 课堂模式：本人创建/被共享 + 年级学科授权命中 + 旧 is_public
            # （仅资源未配置授权记录时生效，保证管理员收紧授权后立即生效）
            audience_ids = teacher_audience_condition(teacher_id)
            query = query.filter(or_(
                base,
                Resource.id.in_(audience_ids),
                _legacy_public_condition()))
        else:
            query = query.filter(base)
    if classroom:
        query = query.filter(Resource.show_in_classroom.is_(True))
    return query




def _active_teaching_teacher_ids(class_id):
    if not class_id:
        return set()
    return {
        tid for (tid,) in db.session.query(TeachingSession.teacher_id).filter(
            TeachingSession.class_id == class_id,
            TeachingSession.end_time.is_(None),
            TeachingSession.teacher_id.isnot(None),
        ).distinct().all()
        if tid
    }


def _class_teacher_ids(class_id):
    """班级任课教师（teacher_class 维护），用于老师尚未在资源上点
    「开始上课」时学生仍能看到任课教师资源。"""
    if not class_id:
        return set()
    rows = db.session.execute(
        teacher_class.select().where(teacher_class.c.class_id == class_id)
    ).fetchall()
    return {row.teacher_id for row in rows if row.teacher_id}


def _scope_teacher_ids(class_id):
    """学生资源范围的教师集合：正在上课的教师优先；没有上课记录时
    回退到该班任课教师（不是全局资源）。"""
    return _active_teaching_teacher_ids(class_id) or _class_teacher_ids(
        class_id)


def classroom_scope_signature(class_id):
    """学生资源范围签名：班级 + 范围教师集合。

    无教师时也返回稳定签名（含 public 标记），用于公开/内置资源列表
    的短 TTL 缓存键；调用方不再用 None 表示“无教师”。
    """
    ids = _scope_teacher_ids(class_id)
    if not ids:
        return f'{class_id or 0}:public'
    return f'{class_id}:' + ','.join(str(i) for i in sorted(ids))


def student_public_resources():
    """学生可见的公开/内置允许公开资源（与授课教师无关）。

    口径：show_in_student=True 且（旧 is_public 且无授权记录，或存在
    「不限年级 × 不限学科」的授权记录——内置资源默认即此通配）。
    """
    wildcard_ids = db.session.query(resource_audience.c.resource_id).filter(
        resource_audience.c.grade.is_(None),
        resource_audience.c.subject_id.is_(None))
    return (Resource.query.filter(
        Resource.show_in_student.is_(True),
        or_(_legacy_public_condition(), Resource.id.in_(wildcard_ids)),
    ).order_by(Resource.id).all())


def _teacher_scoped_resource_ids(teacher_id):
    """某任课教师范围内可学生可见的资源 id（不要求 show_in_student）。

    - 自建 + 被共享资源；共享资源按教师任教学科过滤（未分类保留），
      自建资源不再按学科二次过滤（教师自己的资源即其教学范围）；
    - 管理员年级×学科授权命中（teacher_audience_condition）追加。
    """
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher:
        return set()
    shared_ids = db.session.query(resource_share.c.resource_id).filter(
        resource_share.c.teacher_id == teacher_id)
    own_ids = db.session.query(Resource.id).filter(
        Resource.creator_teacher_id == teacher_id)
    shared_query = Resource.query.filter(Resource.id.in_(shared_ids))
    subject_ids = teacher_subject_ids(teacher_id)
    if subject_ids:
        shared_query = shared_query.filter(or_(
            Resource.subject_id.in_(subject_ids),
            Resource.subject_id.is_(None)))
    ids = {row[0] for row in own_ids.all()}
    ids.update(row[0] for row in
               shared_query.with_entities(Resource.id).all())
    ids.update(row[0] for row in
               teacher_audience_condition(teacher_id).all())
    return ids


def student_classroom_scope(class_id):
    """返回 (teacher_scoped, public) 两组资源（去重、按 id 排序）。

    teacher_scoped：当前上课教师（无上课记录时回退该班任课教师）范围内
    的资源（学生跟随教师，课堂内可用，不要求 show_in_student）；
    public：公开/内置允许公开资源。
    """
    teacher_ids = _scope_teacher_ids(class_id)
    scoped_ids = set()
    for teacher_id in teacher_ids:
        scoped_ids |= _teacher_scoped_resource_ids(teacher_id)
    # 教师范围内仍需至少一个展示开关：both false 视为教师草稿，不向学生
    # 暴露（show_in_classroom=True 支持课堂展示即授权，show_in_student=True
    # 支持教师明确开放给学生自学）。
    teacher_res = (Resource.query.filter(
        Resource.id.in_(scoped_ids),
        or_(Resource.show_in_student.is_(True),
            Resource.show_in_classroom.is_(True)),
    ).order_by(Resource.id).all() if scoped_ids else [])
    public_res = student_public_resources()
    seen = {r.id for r in teacher_res}
    return teacher_res, [r for r in public_res if r.id not in seen]


def student_classroom_scoped_resources(class_id):
    """学生课堂可见资源 = 任课教师范围 + 公开/内置资源（恒返回列表）。

    与旧实现差异：无任课教师时不再返回 None（调用方不再回退全局列表），
    仅返回公开/内置允许公开的资源；教师范围内不要求 show_in_student
    （教师在课堂展示的资源对学生可用）。
    """
    teacher_res, public_res = student_classroom_scope(class_id)
    return teacher_res + public_res


def student_scope_sets(student):
    """学生可访问资源 id 集合：(teacher_scoped_ids, public_ids)。

    静态课件每请求都会调用（一节课几十个 CSS/JS/图片），单次计算包含
    教师集合、自建/共享/授权资源等多条查询；按「范围签名 + 资源写入版本」
    缓存 30 秒，把整页静态请求收敛为 1 次计算。资源/可见性写路径通过
    `study:resources:scope:version` 立即换代；上下课切换最多滞后 30 秒。
    """
    if not student:
        return set(), set()
    from app.extensions import cache
    signature = classroom_scope_signature(student.class_id)
    version = cache.get('study:resources:scope:version') or 0
    key = f'student:scope_sets:{signature}:v{version}'
    cached = cache.get(key)
    if cached is not None:
        teacher_ids, public_ids = cached
        return set(teacher_ids), set(public_ids)
    teacher_res, public_res = student_classroom_scope(student.class_id)
    teacher_ids = {r.id for r in teacher_res}
    public_ids = {r.id for r in public_res}
    cache.set(key, (teacher_ids, public_ids), timeout=30)
    return teacher_ids, public_ids


def student_can_access_resource(resource, student):
    """学生能否访问某资源（列表/直链/预览/文档/课堂页统一口径）。

    仅两类：任课教师范围（自建资源全量，共享资源按任教学科过滤；
    课堂展示的资源即使 show_in_student=False 也可用）与公开/内置允许
    公开资源。范围外资源即使 show_in_student=True 也拒绝，避免学生通过
    已知 URL 遍历全部资源。
    """
    if not resource or not student:
        return False
    teacher_ids, public_ids = student_scope_sets(student)
    return resource.id in teacher_ids or resource.id in public_ids


def resource_creator_label(resource):
    if not resource:
        return ''
    if resource.creator_type == 'teacher':
        return resource.creator_name or '教师'
    return resource.creator_name or '管理员'


def resource_share_teacher_ids(resource_id):
    rows = db.session.execute(
        resource_share.select().where(resource_share.c.resource_id == resource_id)
    ).fetchall()
    return {row.teacher_id for row in rows}
