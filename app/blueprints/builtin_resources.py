# -*- coding: utf-8 -*-
"""内置资源注册表：停用墓碑与恢复入口共用。

内置资源随版本分发，管理员可改元数据、停用/恢复；`builtin_key` 用于种子
幂等与墓碑键。V6.1.0 起铜匠实验室外置到 123/，注册表只保留化学仿真。
"""

BUILTIN_LABELS = {
    'chem_lab': '化学仿真',
}


def suppressed_builtin_items():
    """已被管理员停用（墓碑）的内置资源列表（供管理端恢复入口）。"""
    from app.models import SystemConfig
    return [{'key': key, 'label': label}
            for key, label in BUILTIN_LABELS.items()
            if SystemConfig.get(f'builtin_suppressed:{key}') == '1']


def restore_builtin(key):
    """恢复被停用的内置资源（清除墓碑后重跑种子）。"""
    from app.extensions import db
    from app.models import SystemConfig
    if key not in BUILTIN_LABELS:
        return 0
    SystemConfig.set(f'builtin_suppressed:{key}', '0')
    db.session.commit()
    if key == 'chem_lab':
        from app.blueprints.chem_lab import ensure_chem_lab_resource
        return ensure_chem_lab_resource()
    return 0
