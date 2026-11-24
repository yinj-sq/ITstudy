# -*- coding: utf-8 -*-
"""课堂页章节 iframe 成绩转发回归（2026-10-26）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_lesson_page_forwards_quiz_result_from_link_frame():
    js = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    assert 'setupQuizResultForwarding' in js
    assert "msg.type !== 'ITSTUDY_QUIZ_RESULT'" in js
    assert "'/api/resource_quiz/submit'" in js
    assert 'e.source !== frame.contentWindow' in js
    assert 'setupQuizResultForwarding();' in js
