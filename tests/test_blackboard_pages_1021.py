# -*- coding: utf-8 -*-
"""黑板点按落笔、粉笔色与多页翻页回归（2026-10-21）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_blackboard_dot_colors_and_pages():
    html = (ROOT / 'templates' / 'study_lesson.html').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'js' / 'lesson_tools.js').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'css' / 'study_lesson.css').read_text(encoding='utf-8')

    # 红/黄粉笔必须在页面上有可见颜色（此前只有 data-color，没有背景色）
    assert 'data-color="#FFEB3B" style="background:#FFEB3B"' in html
    assert 'data-color="#FF5252" style="background:#FF5252"' in html
    for dom_id in ('bbPrev', 'bbPageInfo', 'bbNext', 'bbNew'):
        assert f'id="{dom_id}"' in html

    # 点按落笔 + 多页存储/切换
    for marker in ('dot: function (p)', 'getCoalescedEvents', 'pages: [\'\']',
                   'newPage: function ()', 'prevPage: function ()',
                   'nextPage: function ()', 'saveCurrentPage: function ()'):
        assert marker in js, marker

    assert '.bb-page' in css and '.bb-btn:disabled' in css
