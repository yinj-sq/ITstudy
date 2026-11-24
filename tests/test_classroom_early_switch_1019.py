# -*- coding: utf-8 -*-
"""课堂大屏课程表自动切班提前量回归（2026-10-21）。"""
from datetime import datetime
from types import SimpleNamespace as NS

from app.blueprints.classroom import _auto_period_for_now


def _s(start, end):
    return NS(start_time=start, end_time=end, id=1, period_name='第一节')


def test_auto_switch_is_five_minutes_before_start():
    period = _s('08:00', '08:45')
    assert _auto_period_for_now([period], datetime(2026, 10, 21, 7, 54)) is None
    assert _auto_period_for_now([period], datetime(2026, 10, 21, 7, 55)) is period
    assert _auto_period_for_now([period], datetime(2026, 10, 21, 8, 0)) is period
    assert _auto_period_for_now([period], datetime(2026, 10, 21, 8, 45)) is period
    assert _auto_period_for_now([period], datetime(2026, 10, 21, 8, 46)) is None


def test_auto_switch_keeps_current_period_and_ignores_invalid_times():
    current = _s('07:00', '08:00')
    next_period = _s('08:00', '08:45')
    assert _auto_period_for_now([next_period, current],
                                datetime(2026, 10, 21, 7, 55)) is current
    invalid = _s('bad', '08:45')
    assert _auto_period_for_now([invalid], datetime(2026, 10, 21, 7, 55)) is None
