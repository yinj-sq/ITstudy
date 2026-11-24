# -*- coding: utf-8 -*-
"""课堂阅读位置记忆回归（2026-10-22）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_reading_state_markers_present():
    js = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    embed = (ROOT / 'static' / 'pptist' / 'index.html').read_text(encoding='utf-8')
    for marker in ('ReadingState', 'lesson.readpos.v1.', 'restoreFrame',
                   'restorePptx', 'slideState'):
        assert marker in js, marker
    for marker in ('getSlideState', 'gotoSlide', "send('slideState'"):
        assert marker in embed, marker
