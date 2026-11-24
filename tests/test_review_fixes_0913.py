# -*- coding: utf-8 -*-
"""2026-09-13 全面审查修复回归测试

覆盖本轮修复（详见 git show 8d47f69:docs/全面审查报告-2026-09-13.md）：
- P2  存量 deploy.conf 收不到新版本新增配置块 → 启动时自动整块追加（幂等）
- P2  python_fill 每空正确率未复用 _parse_acceptable_answers（'//' 多解口径分叉）
- P2  批改导航（上一名/下一名）漏带教师班级边界 → 连续批改跨班断流

deploy.conf 与判分口径部分为纯函数断言（全在 tmp_path 内，不碰真实配置）；
批改导航部分只构造 SQL 不执行，不写库。

**未覆盖**：scores.py 中 `str(user_answers.get(...))` 的 AttributeError 兜底。
该逻辑内联在趋势页统计的大循环里，无法脱离整页与库单测；在此复刻一份
表达式只会测到副本而非源码。需靠人工/E2E 验证（见报告 §5）。
"""
import pytest

from app import create_app
from app.config import (DEPLOY_CONF_TEMPLATE, _CACHE_TYPE_ALIASES,
                        _deploy_template_blocks, _load_deploy_settings,
                        _merge_missing_deploy_blocks)
from app.services.scoring_service import _parse_acceptable_answers


class _Q:
    """轻量题目替身（仅评分函数所需字段）。"""

    def __init__(self, question_type='python_fill'):
        self.question_type = question_type


# ── deploy.conf 配置块合并 ──────────────────────────────

def test_template_blocks_cover_every_documented_key():
    """模板每个配置块都能被解析出键；文件头说明块键为 None。

    键漏解析 = 该块永远被判为"已存在"或重复追加，是合并逻辑的命门。
    """
    keys = [k for k, _ in _deploy_template_blocks()]

    assert keys[0] is None, '文件头应是纯说明块'
    assert set(k for k in keys if k) == {
        'cache_type', 'cache_dir', 'cookie_secure', 'trusted_hosts',
        'trust_proxy_headers', 'proxy_secret', 'student_ai_private_hosts',
        'login_ip_global_max_fails', 'ai_max_concurrent_streams',
        'waitress_threads',
        'quiz_analysis_cache_seconds', 'large_download_pool_size',
        'large_download_threshold_mb',
    }


def test_merge_appends_missing_block_with_its_comments(tmp_path):
    """存量文件只有 cache_type → 其余 8 块连同说明注释整块补齐。"""
    conf = tmp_path / 'deploy.conf'
    old = ('# ITstudy 部署调优参数（instance/deploy.conf）\n\n'
           '# 缓存后端\ncache_type=simple\n')
    conf.write_text(old, encoding='utf-8')

    merged = _merge_missing_deploy_blocks(str(conf), old)

    assert 'ai_max_concurrent_streams' in merged
    # 不只补键，还要补它的说明注释（运维靠注释才知道怎么调）
    assert '流式' in merged
    assert merged == conf.read_text(encoding='utf-8'), '返回值须与落盘内容一致'
    assert 'cache_type=simple' in merged, '既有生效行原样保留'


def test_merge_is_idempotent(tmp_path):
    """二次启动不得重复追加（否则文件每次启动膨胀一轮）。"""
    conf = tmp_path / 'deploy.conf'
    conf.write_text(DEPLOY_CONF_TEMPLATE, encoding='utf-8')

    once = _merge_missing_deploy_blocks(str(conf), DEPLOY_CONF_TEMPLATE)
    twice = _merge_missing_deploy_blocks(str(conf), once)

    assert once == DEPLOY_CONF_TEMPLATE, '模板本身已齐全，不应改动'
    assert twice == once
    assert once.count('ai_max_concurrent_streams') == 1


def test_merge_treats_commented_key_as_present(tmp_path):
    """用户注释掉的键也算"已存在"，不得再追加模板默认块。

    模板本身就以 `# key=value` 形式给样例行，若只认生效行，
    每次启动都会给所有注释态的键再追加一份。
    """
    conf = tmp_path / 'deploy.conf'
    old = ('cache_type=filesystem\n\n'
           '# 我自己写的说明\n'
           '# ai_max_concurrent_streams=99\n')
    conf.write_text(old, encoding='utf-8')

    merged = _merge_missing_deploy_blocks(str(conf), old)

    assert 'cache_type=filesystem' in merged, '用户改过的值不得被覆盖'
    assert merged.count('ai_max_concurrent_streams') == 1
    assert '# 我自己写的说明' in merged


def test_load_deploy_settings_self_heals_stale_file(tmp_path):
    """端到端：老部署启动一次后，配置文件里就能看到新调优项。"""
    inst = tmp_path / 'instance'
    inst.mkdir()
    (inst / 'deploy.conf').write_text('cache_type=simple\n', encoding='utf-8')

    cfg = _load_deploy_settings(str(tmp_path))

    assert cfg['cache_type'] == 'simple', '合并不得影响取值解析'
    assert 'ai_max_concurrent_streams' in (
        inst / 'deploy.conf').read_text(encoding='utf-8')


def test_load_deploy_settings_creates_template_when_absent(tmp_path):
    """全新安装：文件不存在时整份写出模板（既有行为不得回退）。"""
    cfg = _load_deploy_settings(str(tmp_path))

    # 模板写类名（SimpleCache）而非旧的小写后端名：flask-caching 2.5 起
    # 删除了 backends/__init__.py 的小写垫片，模板若继续写 simple，
    # 全新安装开箱即崩（ImportError）。见下方 test_cache_type_* 系列。
    assert cfg['cache_type'] == 'SimpleCache'
    text = (tmp_path / 'instance' / 'deploy.conf').read_text(encoding='utf-8')
    assert text == DEPLOY_CONF_TEMPLATE


def test_load_deploy_settings_survives_unwritable_conf(tmp_path, monkeypatch):
    """合并写盘失败（只读目录/无权限）不得影响取值，更不得阻断启动。

    _merge_missing_deploy_blocks 在**导入期**执行（Config 类体求值），
    抛异常等于应用起不来。
    """
    inst = tmp_path / 'instance'
    inst.mkdir()
    (inst / 'deploy.conf').write_text('cache_type=filesystem\n',
                                      encoding='utf-8')

    import app.config as cfg_mod
    monkeypatch.setattr(cfg_mod, '_merge_missing_deploy_blocks',
                        lambda p, t: (_ for _ in ()).throw(OSError('boom')))

    assert _load_deploy_settings(str(tmp_path))['cache_type'] == 'filesystem'


# ── 缓存后端名归一化（flask-caching 2.5 兼容）─────────────

def test_cache_type_aliases_resolve_to_real_backends():
    """别名表里的每个类名都必须是 flask-caching 真实存在的后端类。

    flask-caching 2.5 删掉了 backends/__init__.py 的小写垫片函数，
    CACHE_TYPE='simple' 会在 import_string 处抛 ImportError——**应用启动
    即崩**（本机实测装机版 2.5.1：服务起来数秒后挂掉，日志只留一行
    ImportError）。修复是启动时把旧小写名换算成类名，故本表是承重结构：
    类名拼错、或上游再改名，换算结果同样崩，这里逐条对着上游校验。
    """
    from flask_caching import BaseCache
    from werkzeug.utils import import_string

    for legacy, cls_name in _CACHE_TYPE_ALIASES.items():
        cls = import_string(f'flask_caching.backends.{cls_name}')
        assert isinstance(cls, type) and issubclass(cls, BaseCache), \
            f'{legacy} -> {cls_name} 不是 flask-caching 后端类'


@pytest.mark.parametrize('legacy,expected', [
    ('simple', 'SimpleCache'),
    ('filesystem', 'FileSystemCache'),
    ('SIMPLE', 'SimpleCache'),      # 大小写不敏感
])
def test_cache_type_legacy_names_normalized(legacy, expected):
    """存量 deploy.conf 的小写名按归一化规则换算成类名。"""
    assert _CACHE_TYPE_ALIASES.get(legacy.strip().lower(), legacy) == expected


def test_config_cache_type_is_resolvable_class_name():
    """当前生效配置的 CACHE_TYPE 必须能解析成后端类。

    这一条盯的是**实际取值链**（环境变量 > deploy.conf > 默认）——
    归一化若漏在某个分支（如环境变量直传原始值），本进程的
    Config.CACHE_TYPE 就会残留小写名，这里立刻失败。
    """
    from flask_caching import BaseCache
    from werkzeug.utils import import_string

    from app.config import Config

    cls = import_string(f'flask_caching.backends.{Config.CACHE_TYPE}')
    assert isinstance(cls, type) and issubclass(cls, BaseCache)


# ── python_fill 每空统计口径 ──────────────────────────────

@pytest.mark.parametrize('student_answer', ['money', 'm', 'money // m'])
def test_python_fill_multi_answer_accepted(student_answer):
    """'money // m' 一空多解：三种写法判分器都收，统计口径必须一致。

    修复前趋势页只按 '|' 拆 → 仅整串算对，答 money 的学生判分满分
    却被统计为答错，教师看到的每空正确率恒偏低。
    """
    assert student_answer in _parse_acceptable_answers('money // m', _Q())


def test_python_fill_integer_division_not_split():
    """python_fill 的整除表达式 'a//b' 不得被拆成多解。"""
    acceptable = _parse_acceptable_answers('a//b', _Q('python_fill'))

    assert 'a//b' in acceptable
    assert 'a' not in acceptable and 'b' not in acceptable


def test_pipe_separated_answers_still_split():
    """'|' 多空分隔的既有语义不受影响。"""
    acceptable = _parse_acceptable_answers('x|y', _Q())

    assert 'x' in acceptable and 'y' in acceptable


# ── 批改导航班级边界 ──────────────────────────────

@pytest.fixture(scope='module')
def app():
    """仅用于提供 app context（Result.query 构造所需）。

    本模块只构造 SQL 不执行，不产生任何库写入。
    """
    return create_app()


def test_grading_nav_query_applies_teacher_boundary(app, monkeypatch):
    """教师身份下，导航查询必须带上 student_id 边界条件。

    列表页已按班级过滤，导航若不过滤会把教师带到外班学生页再被
    grade_student 弹回，连续批改断流（非越权，是可用性缺陷）。
    """
    from app.blueprints import grading
    monkeypatch.setattr(grading, '_teacher_visible_student_ids',
                        lambda: [11, 22])

    with app.app_context():
        sql = str(grading._grading_nav_query(7)).replace('\n', ' ')

    assert 'student_id IN' in sql
    assert 'exam_id' in sql


def test_grading_nav_query_admin_sees_all(app, monkeypatch):
    """管理员不受班级边界约束（_teacher_visible_student_ids 返回 None）。"""
    from app.blueprints import grading
    monkeypatch.setattr(grading, '_teacher_visible_student_ids',
                        lambda: None)

    with app.app_context():
        sql = str(grading._grading_nav_query(7)).replace('\n', ' ')

    assert 'student_id IN' not in sql
    assert 'exam_id' in sql


def test_grading_nav_query_fail_closed_without_active_class(app, monkeypatch):
    """教师未设置上课班级时返回空列表 → 导航查询同样 fail-closed。"""
    from app.blueprints import grading
    monkeypatch.setattr(grading, '_teacher_visible_student_ids', lambda: [])

    with app.app_context():
        sql = str(grading._grading_nav_query(7)).replace('\n', ' ')

    assert 'student_id IN' in sql
