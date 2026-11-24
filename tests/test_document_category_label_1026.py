# -*- coding: utf-8 -*-
"""电子文档分类标签：讲义 → 教材分析（2026-10-26）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_handout_category_label_is_textbook_analysis():
    editor = (ROOT / 'static' / 'js' / 'lesson_editor.js').read_text(encoding='utf-8')
    tools = (ROOT / 'static' / 'js' / 'lesson_tools.js').read_text(encoding='utf-8')
    assert "['handout', '教材分析']" in editor
    assert "{ key: 'handout', label: '教材分析'" in tools
    assert "'讲义'" not in editor
    assert "label: '讲义'" not in tools
