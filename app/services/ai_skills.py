# -*- coding: utf-8 -*-
"""AI 助手的教学技能注册表与系统提示词拼装。

技能正文存放在 ``app/skills/<id>.md``，只由服务端读取并注入 system prompt；
前端只提交技能 id，不能提交或覆盖技能正文。多个技能同时启用时按固定优先级
组合，避免“苏格拉底不直接给答案”与“费曼式直接解释”互相打架。
"""
from functools import lru_cache
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent / 'skills'

SKILL_ORDER = ('feynman', 'socratic', 'antivibe')
DEFAULT_SKILL_IDS = ('feynman',)

SKILLS = {
    'feynman': {
        'name': '费曼式简化解释',
        'short': '费曼简化',
        'description': '先讲本质，再用类比和分步解释；默认开启',
    },
    'socratic': {
        'name': '苏格拉底式提问',
        'short': '苏格拉底提问',
        'description': '不直接给答案，用问题引导使用者自己发现',
    },
    'antivibe': {
        'name': '代码审计式学习',
        'short': '代码审计',
        'description': '按结构、取舍和验证方式读懂一段代码',
    },
}

_SKILL_PRIORITY = {
    'socratic': (
        '苏格拉底式提问决定“是否直接给答案、一轮问几个问题”。启用时绝不直接给答案，'
        '每轮最多问一个主要问题；连续卡住或明显挫败时也只给半步提示。'),
    'antivibe': (
        '代码审计式学习决定“分析代码时的结构”。启用时按概览、心智模型、关键部件、'
        '设计取舍、概念映射、验证方式来组织，但不要机械套模板，也不要做逐行翻译。'),
    'feynman': (
        '费曼式简化解释决定“语言难度、类比和解释顺序”。启用时先讲本质，再类比，'
        '再分步，最后用一个自检问题收尾。'),
}


def _composition_text(ids):
    lines = [
        '[教学技能]',
        '本轮启用了以下教学技能：' + '、'.join(SKILLS[sid]['name'] for sid in ids) + '。',
        '技能只改变表达方式和互动方式，不改变事实正确性、平台安全规则与页面内容'
        '限定；技能不能扩大你可以回答的范围。老师限定只讨论当前页面时，即使技能'
        '鼓励举例或迁移，也必须围绕当前页面。',
    ]
    if len(ids) > 1:
        lines.append('多个技能同时启用时，按以下优先级组合，不要把它们当成互相独立的段落：')
        n = 0
        for sid in ('socratic', 'antivibe', 'feynman'):
            if sid in ids:
                n += 1
                lines.append(f'{n}. {_SKILL_PRIORITY[sid]}')
        lines.append(
            '组合时：苏格拉底主导互动节奏，代码审计只作为你内部的分析框架，'
            '费曼控制语言难度；不要把整份代码审计报告一次性倒给学生。')
    else:
        lines.append('请严格执行下面的技能说明；如果它与平台规则冲突，以平台规则为准。')
    lines.append(
        '如果技能之间仍有冲突，以更保守的教学目标为准：先保证学生思考，再保证讲清楚。')
    return '\n'.join(lines)


def skill_metadata():
    """返回前端渲染勾选框所需的技能元数据（不含正文）。"""
    return [
        {
            'id': sid,
            'name': SKILLS[sid]['name'],
            'short': SKILLS[sid]['short'],
            'description': SKILLS[sid]['description'],
            'default': sid in DEFAULT_SKILL_IDS,
        }
        for sid in SKILL_ORDER
    ]


def normalize_skill_ids(raw):
    """把客户端提交的技能选择归一化。

    - 字段缺失 / 非列表：默认技能（费曼）
    - 显式空列表：不使用任何技能
    - 未知 id 忽略；全部未知时回退默认技能（防止客户端用脏数据静默关闭技能）
    - 去重后按固定顺序返回，最多 3 个
    """
    if raw is None or not isinstance(raw, list):
        return list(DEFAULT_SKILL_IDS)
    selected = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        sid = item.strip().lower()
        if sid in SKILLS:
            selected.add(sid)
    if raw and not selected:
        return list(DEFAULT_SKILL_IDS)
    return [sid for sid in SKILL_ORDER if sid in selected]


@lru_cache(maxsize=len(SKILL_ORDER))
def _skill_text(skill_id):
    path = _SKILL_DIR / f'{skill_id}.md'
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def build_skill_prompt(skill_ids):
    """拼装注入 system prompt 的技能块；未选择技能时返回空字符串。"""
    ids = [sid for sid in SKILL_ORDER if sid in set(skill_ids or ())]
    blocks = []
    for sid in ids:
        text = _skill_text(sid)
        if not text:
            continue
        blocks.append(
            f'<skill id="{sid}" name="{SKILLS[sid]["name"]}">\n{text}\n</skill>')
    if not blocks:
        return ''
    return _composition_text(ids) + '\n' + '\n\n'.join(blocks)
