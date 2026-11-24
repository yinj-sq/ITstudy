# -*- coding: utf-8 -*-
"""课堂页倒计时/秒表模式回归（2026-10-21）。

秒表原本能走，但切换到秒表后预设按钮仍显示、界面没有模式标识，
用户很容易再点回倒计时，表现为"秒表模式不可用"。本组锁定：
模式标签/按钮状态、秒表十分之一秒显示、预设隐藏与切换回倒计时。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_timer_stopwatch_mode_ui():
    js = (ROOT / 'static' / 'js' / 'lesson_tools.js').read_text(encoding='utf-8')
    html = (ROOT / 'templates' / 'study_lesson.html').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'css' / 'study_lesson.css').read_text(encoding='utf-8')

    # 模板：模式标签 + 可访问状态
    assert 'id="timerModeLabel"' in html
    assert 'id="timerStopwatch" aria-pressed="false"' in html

    # 脚本：模式同步、秒表十分之一秒、切回倒计时
    for marker in ('syncModeUi', 'fmtStopwatch', "isStopwatch ? '倒计时模式' : '秒表模式'",
                   'var period = this.mode === \'stopwatch\' ? 100 : 250',
                   'this.syncModeUi();\n      this.render();'):
        assert marker in js, marker

    # 样式：秒表模式下隐藏倒计时预设，按钮有激活态
    assert '.timer-box.stopwatch .tm-presets { display: none; }' in css
    assert '.tm-btn.active' in css
