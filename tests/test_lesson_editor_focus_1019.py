# -*- coding: utf-8 -*-
"""课堂编排器打开时自动定位当前资源（2026-10-21）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_edit_resource_passes_current_file_to_editor():
    src = (ROOT / 'templates' / 'edit_resource.html').read_text(encoding='utf-8')
    assert 'currentFile: {{ current_file|tojson }}' in src


def test_lesson_editor_focuses_current_resource_section():
    src = (ROOT / 'static' / 'js' / 'lesson_editor.js').read_text(encoding='utf-8')
    assert 'focusCurrentSection' in src
    assert 'DATA.currentFile' in src
    assert 'scrollIntoView' in src
