# -*- coding: utf-8 -*-
"""课堂工具栏折叠与教师 AI 面板加载回归（2026-10-22）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_toolbar_can_collapse():
    html = (ROOT / 'templates' / 'study_lesson.html').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'css' / 'study_lesson.css').read_text(encoding='utf-8')
    assert 'id="lessonToolbarToggle"' in html
    assert 'id="lessonToolbarItems"' in html
    assert 'setToolbarCollapsed' in js
    assert "lesson.toolbarCollapsed" in js
    assert '.lesson-toolbar.collapsed .lesson-toolbar-items { display: none; }' in css


def test_teacher_pages_load_ai_panel():
    base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    marker = "session.get('is_teacher') or classroom_mode"
    assert marker in base
