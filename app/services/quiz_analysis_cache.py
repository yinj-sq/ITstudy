# -*- coding: utf-8 -*-
"""逐题分析结果短缓存（默认 45s，`quiz_analysis_cache_seconds` 可调）。

`/admin/resources/quiz_analysis/<id>` 每次请求都会把该资源某一来源页的
全部答卷载入内存重新聚合。班级规模（≤60 人）开销很小，但同一资源跨多年
累积到数千份后，每次打开分析页都要全量重算。这里按「资源 + 来源页」缓存
聚合结果：

- 版本号按资源维护，成绩提交/删除、学生删除、资源删除或铜匠入口迁移时
  立即 ``invalidate``，旧条目在 TTL 后自然淘汰；
- 缓存是尽力而为：后端异常时回退为直接计算，不影响分析页可用性；
- 来源页文件名先做摘要再拼键，避免长文件名/特殊字符影响缓存后端。
"""
import hashlib

from app.extensions import cache

_VERSION_KEY = 'quiz_analysis:ver:{}'
_ENTRY_KEY = 'quiz_analysis:{}:{}:{}'
_VERSION_TTL = 86400


def _version(resource_id):
    try:
        value = cache.get(_VERSION_KEY.format(resource_id))
        return int(value) if value is not None else 0
    except Exception:
        return 0


def _entry_key(resource_id, source_file):
    try:
        digest = hashlib.sha1(
            (source_file or '').encode('utf-8')).hexdigest()[:16]
        return _ENTRY_KEY.format(int(resource_id), _version(resource_id), digest)
    except Exception:
        return None


def invalidate_analysis(resource_id):
    """让该资源的全部分析缓存立即失效（版本号 +1）。"""
    if not resource_id:
        return
    try:
        cache.set(_VERSION_KEY.format(resource_id), _version(resource_id) + 1,
                  timeout=_VERSION_TTL)
    except Exception:
        pass


def get_analysis(resource_id, source_file):
    """返回缓存的分析结果；未命中或缓存不可用时返回 None。"""
    key = _entry_key(resource_id, source_file)
    if not key:
        return None
    try:
        return cache.get(key)
    except Exception:
        return None


def set_analysis(resource_id, source_file, data, timeout):
    """缓存分析结果；timeout<=0 时不做任何事。"""
    if not timeout or timeout <= 0:
        return
    key = _entry_key(resource_id, source_file)
    if not key:
        return
    try:
        cache.set(key, data, timeout=timeout)
    except Exception:
        pass
