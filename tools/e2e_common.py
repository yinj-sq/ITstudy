# -*- coding: utf-8 -*-
"""E2E 脚本共用：隔离库防护与共享状态复位（开发期工具，不随安装包/镜像分发）。

背景（2026-11-11 审查实测）：全部 e2e_* 脚本共用隔离库 itstudy_e2e，而课堂会话、
教师只读访问码、系统开关是**全库共享状态**。任一脚本中途崩溃（没走到清理）
就会把状态留给后面的脚本：

- 残留的活跃 ClassroomSession 让「只设置旧版 ClassroomSetting」的脚本里学生
  无法登录（_get_active_class_ids 优先取会话表，回退分支永远走不到）；
- 残留的只读访问码让教师登录页默认勾选只读模式，密码框被隐藏；
- 残留的维护开关 / 「学生限本页」开关直接改变学生端行为。

一次崩溃曾连带 6 个脚本失败，且现象与真实缺陷无法区分。每个脚本在建夹具
之前调用 reset_shared_state(app)，把这些状态复位到默认值。

文件名保持 e2e_ 前缀：installer.nsi 与 .dockerignore 按 `e2e_*.py` 排除开发脚本。
"""

# 只允许在隔离库上复位：这里的语句是整表/整键删除，绝不能落到业务库
ISOLATED_DB_NAMES = ('itstudy_e2e', 'itstudy_test')

# 会被各脚本改写、且会影响其他脚本行为的系统开关（删除即回到代码默认值）
_SHARED_CONFIG_KEYS = (
    'teacher_readonly_code_hash',   # 非空时教师登录页默认只读模式
    'ai_student_page_only',         # 学生 AI 仅限当前页面
    'student_access_enabled',       # 学生端维护模式
    'courseware_public_enabled',    # 课件匿名访问
    'class_buttons_enabled',        # 上课/下课按钮
)


def assert_isolated_db(app):
    """解析出的数据库不是隔离库时直接终止（防止误连业务库）。"""
    name = str(app.config.get('DB_NAME') or '')
    if name not in ISOLATED_DB_NAMES:
        raise SystemExit(
            f'拒绝运行：解析出的数据库为 {name!r}，不是隔离库 {ISOLATED_DB_NAMES}')
    return name


def reset_shared_state(app):
    """把全库共享状态复位到默认值；仅限隔离库，幂等。

    不删除班级/学生等夹具行——那些由各脚本按自己的命名前缀清理；这里只处理
    「别的脚本留下、会改变本脚本行为」的状态。
    """
    assert_isolated_db(app)
    from sqlalchemy import text
    from app.extensions import db
    from app.models import SystemConfig
    with app.app_context():
        db.session.execute(text('DELETE FROM classroom_session'))
        db.session.execute(text('DELETE FROM classroom_setting'))
        db.session.execute(
            text('DELETE FROM system_config WHERE key = ANY(:keys)'),
            {'keys': list(_SHARED_CONFIG_KEYS)})
        # 内置资源被上次运行停用（墓碑）时，依赖它的脚本会找不到资源
        db.session.execute(text(
            "DELETE FROM system_config WHERE key LIKE 'builtin_suppressed:%'"))
        db.session.commit()
        SystemConfig._invalidate_cache()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


def uncheck_readonly_mode(page):
    """教师登录页：确保处于编辑模式（密码框可见）。

    管理员配置过只读访问码时登录页默认勾选只读模式并隐藏密码框，
    直接 fill 密码会一直等到超时。
    """
    mode = page.locator('#readonlyMode')
    if mode.count() and mode.is_enabled() and mode.is_checked():
        mode.uncheck()
