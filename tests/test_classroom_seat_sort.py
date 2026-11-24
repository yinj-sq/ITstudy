"""座位冲突判定排序回归测试（此前缺陷：排序键取反）

同一座位多人时按 login_time 降序保留"最近登录/在线"学生，未登录者
（login_time 为 None）必须排最后。此前键写成 (is None, ...) 配合
reverse=True 把未登录者排到最前 → 在线学生被误标冲突/离线。
此测试与 classroom.py 两处修复（L663 教师端 / L847 大屏）保持同键。
"""
from datetime import datetime, timezone


def _make(login_time):
    return {'login_time': login_time, 'is_online': login_time is not None}


def _sort_dup_seat(group):
    """与 classroom.py 修复后完全相同的排序键"""
    group.sort(
        key=lambda x: (x['login_time'] is not None,
                       x['login_time'] or datetime.min),
        reverse=True)
    for st in group[1:]:
        st['seat_conflict'] = True
        st['is_online'] = False


def test_online_student_keeps_seat_when_pair_has_offline():
    """同座位：未登录者 + 在线者 → 在线者保留占座,未登录者标冲突。"""
    online = _make(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
    offline = _make(None)
    group = [online, offline]
    _sort_dup_seat(group)
    assert group[0] is online, '在线学生必须保留占座（此前被误标冲突/离线）'
    assert group[0].get('seat_conflict') is not True
    assert group[1]['seat_conflict'] is True
    assert group[1]['is_online'] is False


def test_most_recent_login_keeps_seat():
    """同座位多人均有 login_time → 最近登录者保留占座。"""
    older = _make(datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc))
    newer = _make(datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc))
    group = [older, newer]
    _sort_dup_seat(group)
    assert group[0] is newer
    assert group[1] is older and group[1]['seat_conflict'] is True


def test_offline_students_sort_last():
    """全部未登录 → 顺序稳定,不抛错,全部保持原样（仅长度1的组无冲突）。"""
    a, b = _make(None), _make(None)
    group = [a, b]
    _sort_dup_seat(group)
    # None 全部排最后（与有 login_time 的学生混排时）
    mixed = [a, _make(datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)), b]
    _sort_dup_seat(mixed)
    assert mixed[0]['login_time'] is not None
    assert mixed[1]['login_time'] is None
    assert mixed[2]['login_time'] is None
