"""由 API 门面模块加载的领域路由。"""

from flask import current_app, jsonify, request

from app.extensions import cache, db
from app.models import (
    Resource, ResourceQuizResult, TeachingSession, LearningActivity, Student,
    StudentWork,
)
from app.decorators import admin_login_required, api_login_required
from app.services.log_service import add_log
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Resources
# ──────────────────────────────────────────────


def _is_allowed_resource_url(url):
    """资源链接白名单：http(s) 外链或站内课件路径（与 HTML 路径同口径）。

    站内路径额外拒绝目录漂移形态（`/static/uploads/../` 之类），避免把
    url 变成可穿越 / 可注入的属性值。
    """
    url = url or ''
    if url.startswith(('http://', 'https://')):
        return True
    return url.startswith('/static/uploads/') and '..' not in url.split('/')


@api_bp.route('/resources', methods=['GET'])
@api_login_required
def get_resources():
    """资源列表。

    数据边界：学生仅可见「任课教师范围 + 公开/内置允许公开」的资源
    （此前不过滤可见性，学生可枚举全部隐藏资源的标题与外链 URL，且与
    学生端 /study 页面语义不一致）；管理员/教师可见全部。
    缓存键按角色/范围区分。
    """
    from flask import session as _sess
    is_admin = bool(_sess.get('is_admin'))
    is_teacher = bool(_sess.get('is_teacher'))
    if is_teacher and not is_admin:
        from app.services.resource_access import teacher_visible_resources
        resources = teacher_visible_resources(
            _sess.get('teacher_id'), is_admin=False,
            mode=_sess.get('teacher_mode') or 'edit', classroom=True
        ).order_by(Resource.id).all()
        return jsonify({'success': True, 'data': [
            {'id': r.id, 'title': r.title, 'url': r.url} for r in resources],
            'message': 'ok'})
    is_admin_or_teacher = is_admin or is_teacher
    if not is_admin_or_teacher:
        student_id = _sess.get('student_id')
        if student_id:
            from app.services.resource_access import (
                classroom_scope_signature, student_classroom_scoped_resources)
            student = db.session.get(Student, student_id)
            scope_sig = classroom_scope_signature(
                student.class_id if student else None)
            version = cache.get('study:resources:scope:version') or 0
            scoped_key = f'api:resources:scope:{scope_sig}:v{version}'
            cached_scope = cache.get(scoped_key)
            if cached_scope is not None:
                return jsonify(cached_scope)
            # 学生仅可见：任课教师范围 + 公开/内置
            scoped = student_classroom_scoped_resources(
                student.class_id if student else None)
            result = {
                'success': True,
                'data': [{'id': r.id, 'title': r.title, 'url': r.url}
                         for r in scoped],
                'message': 'ok'
            }
            cache.set(scoped_key, result, timeout=30)
            return jsonify(result)
    cache_key = 'api:resources:list:admin' if is_admin_or_teacher else 'api:resources:list:student'
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)
    query = Resource.query.order_by(Resource.id)
    if not is_admin_or_teacher:
        query = query.filter(Resource.show_in_student.is_(True))
    resources = query.all()
    data = [{'id': r.id, 'title': r.title, 'url': r.url} for r in resources]
    result = {'success': True, 'data': data, 'message': 'ok'}
    cache.set(cache_key, result, timeout=120)
    return jsonify(result)


@api_bp.route('/resources', methods=['POST'])
@admin_login_required
def create_resource():
    """添加资源"""
    data = request.get_json(force=True, silent=True) or request.form
    title = data.get('title', '').strip()
    url = data.get('url', '').strip()
    if not title or not url:
        return jsonify({'success': False, 'message': '标题和链接不能为空'}), 400
    # URL 白名单（与 HTML 路径 admin_resources 同口径）：仅 http(s) 外链或
    # 站内课件路径。此前 API 创建/编辑仅判空即入库，resource.url 会被模板
    # 渲染成 href——`javascript:` 等危险协议可致存储型 XSS（管理员权限面，
    # 与 HTML 口径齐平消除分叉）
    if not _is_allowed_resource_url(url):
        return jsonify({'success': False,
                        'message': '资源链接仅支持 http(s) 外链或站内课件路径'}), 400
    try:
        from flask import session as _sess
        resource = Resource(title=title, url=url, creator_type='admin',
                            creator_name=_sess.get('admin_name') or '管理员')
        db.session.add(resource)
        add_log(user_id=0, user_type='admin',
                action='添加学习资源',
                detail=f'资源标题: {title}')
        db.session.commit()
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        # 与 GET /resources 的角色区分缓存键一致（此前失效的是不存在的
        # 'api:resources:list'，列表最长 120s 陈旧，与删除立即可见不一致）
        cache.delete('api:resources:list:admin')
        cache.delete('api:resources:list:student')
        current_app.logger.info(f"API 添加资源成功: {title}")
        return jsonify({
            'success': True,
            'data': {'id': resource.id, 'title': title, 'url': url},
            'message': '学习资源已添加'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 添加资源失败: {str(e)}")
        return jsonify({'success': False, 'message': '添加资源失败'}), 500


@api_bp.route('/resources/<int:res_id>', methods=['PUT'])
@admin_login_required
def update_resource(res_id):
    """编辑资源"""
    resource = db.get_or_404(Resource, res_id)
    data = request.get_json(force=True, silent=True) or request.form
    title = data.get('title', '').strip()
    url = data.get('url', '').strip()
    if not title or not url:
        return jsonify({'success': False, 'message': '标题和链接不能为空'}), 400
    # URL 白名单（与 HTML 路径 admin_resources 同口径）：仅 http(s) 外链或
    # 站内课件路径。此前 API 创建/编辑仅判空即入库，resource.url 会被模板
    # 渲染成 href——`javascript:` 等危险协议可致存储型 XSS（管理员权限面，
    # 与 HTML 口径齐平消除分叉）
    if not _is_allowed_resource_url(url):
        return jsonify({'success': False,
                        'message': '资源链接仅支持 http(s) 外链或站内课件路径'}), 400
    try:
        resource.title = title
        resource.url = url
        add_log(user_id=0, user_type='admin',
                action='编辑学习资源',
                detail=f'资源ID: {res_id}, 新标题: {title}')
        db.session.commit()
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        # 与 GET /resources 的角色区分缓存键一致（此前失效的是不存在的键）
        cache.delete('api:resources:list:admin')
        cache.delete('api:resources:list:student')
        # 课件目录鉴权映射（dir_map TTL 300s，编辑后不失效则直链鉴权最长
        # 滞后 5 分钟，被取消可见性的课件仍可下载）
        cache.delete('courseware:dir_map')
        current_app.logger.info(f"API 修改资源成功: ID={res_id}")
        return jsonify({
            'success': True,
            'data': {'id': res_id, 'title': title, 'url': url},
            'message': '修改成功'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 修改资源失败: {str(e)}")
        return jsonify({'success': False, 'message': '修改失败'}), 500


@api_bp.route('/resources/<int:res_id>', methods=['DELETE'])
@admin_login_required
def delete_resource(res_id):
    """删除资源（与 Web 版 delete_resource 清理链路一致）"""
    resource = db.get_or_404(Resource, res_id)
    dir_name = None
    if resource.url and resource.url.startswith('/static/uploads/'):
        url_path = resource.url.replace('/static/uploads/', '', 1)
        parts = url_path.split('/')
        if len(parts) >= 1:
            dir_name = parts[0]
    # 收集活动作品磁盘路径（位于资源目录之外，DB 删除后磁盘文件需单独清理）
    activity_ids = [a.id for a in LearningActivity.query.filter_by(
        resource_id=res_id).all()]
    work_disk = []
    if activity_ids:
        work_disk += [w.file_path for w in StudentWork.query.filter(
            StudentWork.activity_id.in_(activity_ids)).all() if w.file_path]
    from app.blueprints.resources import _resource_dir_deletable
    rm_dir = dir_name if _resource_dir_deletable(dir_name, res_id) else None
    try:
        title = resource.title
        # 先清理引用该资源的子表记录（FK 无级联，不清理会在 commit 时抛
        # IntegrityError → 删除必 500，此前缺陷）：内嵌测验成绩 + 上课教学记录
        ResourceQuizResult.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
        from app.services import quiz_analysis_cache
        quiz_analysis_cache.invalidate_analysis(res_id)
        TeachingSession.query.filter_by(resource_id=res_id).delete(synchronize_session=False)
        # 问卷/答卷 FK 无级联：先删答卷再删问卷，否则删除资源 500
        from app.models import Survey, SurveyAnswer
        survey_ids = [s.id for s in Survey.query.filter_by(resource_id=res_id).all()]
        if survey_ids:
            SurveyAnswer.query.filter(
                SurveyAnswer.survey_id.in_(survey_ids)).delete(
                synchronize_session=False)
            Survey.query.filter(Survey.id.in_(survey_ids)).delete(
                synchronize_session=False)
        db.session.delete(resource)
        add_log(user_id=0, user_type='admin',
                action='删除学习资源',
                detail=f'资源标题: {title}')
        db.session.commit()
        # 缓存失效：与 get_resources 写入的角色区分键一致
        # （此前失效的是不存在的 'api:resources:list'，资源列表最长 120s 陈旧）
        cache.delete('study:resources:student')
        cache.delete('study:resources:classroom')
        cache.delete('api:resources:list:admin')
        cache.delete('api:resources:list:student')
        if dir_name:
            cache.delete(f'study:files:{dir_name}')
        # 课件目录鉴权映射随资源删除立即失效（同 update 路径）
        cache.delete('courseware:dir_map')
        current_app.logger.info(f"API 删除资源成功: ID={res_id}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除资源失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除失败'}), 500
    # DB 提交成功后再删磁盘（失败仅残留孤儿目录，不影响功能）
    import os
    import shutil
    uploads_root = os.path.realpath(
        os.path.join(current_app.config.get('BASE_DIR', ''), 'static', 'uploads'))
    if rm_dir:
        try:
            dir_path = os.path.realpath(os.path.join(uploads_root, rm_dir))
            if dir_path != uploads_root and dir_path.startswith(uploads_root + os.sep) \
                    and os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
        except OSError as e:
            current_app.logger.warning(
                f'API 删除资源磁盘目录失败（忽略）: {dir_name}, error={e}')
    if work_disk:
        try:
            from app.utils import delete_file_from_disk as _delete_file
            for rel in work_disk:
                try:
                    _delete_file(rel)
                except Exception:
                    pass
        except Exception:
            current_app.logger.warning('API 删除资源活动作品磁盘文件失败（忽略）')
    # 活动文档按**资源** id 存放（activity_docs/<res_id>/），见 resources.py 同名处
    from app.blueprints.resources import _remove_activity_docs_dir
    _remove_activity_docs_dir(res_id)
    return jsonify({'success': True, 'message': '学习资源已删除'})

