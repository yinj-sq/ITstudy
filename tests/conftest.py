# -*- coding: utf-8 -*-
"""pytest 全局前置：把整套测试钉在独立测试库 itstudy_test 上。

**为什么必须有这个文件**（2026-09-13 审查报告 §9 #5，原文见
`git show 8d47f69:docs/全面审查报告-2026-09-13.md`）：
`app/config.py` 的库名取值链是「环境变量 DB_NAME > postgresql.txt > 内置默认」，
内置默认恰是**生产库 itstudy**；而 tests/ 下 41 处 `create_app()` 全是无参调用
（`app.config.from_object(Config)` ⇒ 直吃这条取值链），无人设置 DB_NAME，
于是全量 pytest 一直在生产库上建表、写卷、写学生、写 log——测试的每一次
清理失效都会永久沉积进生产数据（已发生两次、机制各异，见
tools/review_db_residue_check.py 开头）。

**做法**：conftest.py 由 pytest 在导入任何测试模块**之前**加载，模块顶层
（任何 app 导入之前）设置环境变量即可让全套件统一转向；空库由本文件先建，
首次 `create_app()` 内的 `db.create_all()` 会自动补齐全部表。
同时把 CACHE_DIR 隔离到系统临时目录：它默认落在 data/cache，与主库共用同一批
缓存键（lookup:classes 等），测试数据写进去会污染真实缓存命中。

**防呆闸**（宁可整套测试当场报错，也不许连上生产库）：
导入期直接校验 `Config.SQLALCHEMY_DATABASE_URI`——这正是 create_app() 原样
加载的连接串，库名不是 itstudy_test 即中止。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TEST_DB_NAME = 'itstudy_test'
PROD_DB_NAMES = ('itstudy',)   # 出现即拒绝运行：测试绝不写生产库
_SESSION_LOG_MAX_ID = 0        # 会话开始时 log 表最大 id（结束时只删新增行）

# ── 必须早于任何 app 导入：覆盖 config 取值链的两条环境变量 ──
os.environ['DB_NAME'] = TEST_DB_NAME
os.environ['CACHE_DIR'] = os.path.join(tempfile.gettempdir(), 'itstudy_test_cache')

from app.config import Config        # noqa: E402  —— 必须在设置环境变量之后导入

_dbname = Config.SQLALCHEMY_DATABASE_URI.rsplit('/', 1)[-1]
if _dbname != TEST_DB_NAME or _dbname in PROD_DB_NAMES:
    raise RuntimeError(
        f'测试库名解析为 [{_dbname}]，不是测试库 [{TEST_DB_NAME}]，拒绝运行。\n'
        f'  解析后的连接串：{Config.SQLALCHEMY_DATABASE_URI}\n'
        f'  请检查 DB_NAME 环境变量与仓库/安装目录下的 postgresql.txt。'
    )


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """测试间清空应用缓存：SimpleCache 是进程内全局对象，上一用例写入的
    资源范围/列表缓存会泄漏到下一用例（V6.0 新增 student_scope_sets 缓存后
    实测会让 resource_audience 用例读到旧范围）。隔离后每个用例从空缓存开始。
    """
    try:
        from app.extensions import cache
        cache.clear()
    except Exception:
        pass
    yield
    try:
        cache.clear()
    except Exception:
        pass


def _ensure_test_db():
    """不存在则建空库（幂等）。

    连接参数取与 app 同一份解析（Config.DB_*），避免测试库和应用连到
    不同实例；连 postgres 维护库执行 CREATE DATABASE。
    """
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = psycopg2.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASS, dbname='postgres',
    )
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (TEST_DB_NAME,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        cur.close()
    finally:
        conn.close()


def _log_max_id():
    """当前测试库 log 表最大 id；表不存在/连接失败返回 0。

    用于会话结束时只删除**本次 pytest 新增**的审计日志：测试业务夹具
    清理已覆盖主表，但审计日志（保存思维导图、删除学生作品、资源授权等）
    是清理盲区，会在 itstudy_test 永久沉积并被残留检查报出。
    """
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
            password=Config.DB_PASS, dbname=TEST_DB_NAME,
        )
        try:
            cur = conn.cursor()
            try:
                cur.execute('SELECT COALESCE(MAX(id), 0) FROM log')
                return cur.fetchone()[0]
            except Exception:
                conn.rollback()
                return 0
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception:
        return 0


def _purge_session_logs(min_id):
    """删除本次会话新增的审计日志；只碰隔离库。"""
    if not min_id:
        return
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
            password=Config.DB_PASS, dbname=TEST_DB_NAME,
        )
        try:
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn.cursor()
            cur.execute('DELETE FROM log WHERE id > %s', (min_id,))
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass


def pytest_sessionstart(session):
    """会话开始：确保空库存在，并把实际库名写进终端（事后可追查跑在哪个库上）。"""
    _ensure_test_db()
    global _SESSION_LOG_MAX_ID
    _SESSION_LOG_MAX_ID = _log_max_id()
    tr = session.config.pluginmanager.get_plugin('terminalreporter')
    if tr is not None:
        tr.write_line(
            f'[conftest] 测试库：{TEST_DB_NAME}'
            f'（生产库 {"、".join(PROD_DB_NAMES)} 已隔离；'
            f'缓存目录：{os.environ["CACHE_DIR"]}）'
        )


def pytest_sessionfinish(session, exitstatus):
    """会话结束：删除本次 pytest 写入的审计日志（主表夹具已各自清理）。"""
    _purge_session_logs(_SESSION_LOG_MAX_ID)
