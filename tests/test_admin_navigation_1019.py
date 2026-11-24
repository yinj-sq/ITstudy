# -*- coding: utf-8 -*-
"""管理员导航重组回归（2026-10-21）。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _admin_block(src):
    return src[src.index("{% if session.get('is_admin') %}"):
               src.index("{% elif session.get('is_teacher') %}")]


def _admin_hrefs(src, admin_only=True):
    block = _admin_block(src) if admin_only else src
    return re.findall(r'href="(/admin/[^"]+)"', block)


def test_admin_nav_menu_groups_and_order():
    src = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    admin = _admin_block(src)
    assert '学生管理' not in admin
    assert 'href="/admin/dashboard"' in admin and '管理总览' in admin
    assert admin.index('班级与考勤') < admin.index('教学资源') < admin.index('课堂工具') \
        < admin.index('数据与审计') < admin.index('系统')
    class_block = admin[admin.index('class="dropdown-item" href="/admin/classes"'):]
    for href in ('/admin/classes', '/admin/groups', '/admin/attendance',
                 '/admin/online_students', '/admin/student-drive'):
        assert href in class_block
    data_block = admin[admin.index('href="/admin/students"'):
                       admin.index('<!-- 系统管理 -->')]
    expected = ('/admin/students', '/admin/schedule', '/admin/class_schedule',
                '/admin/statistics', '/admin/teaching-sessions')
    assert [data_block.index(x) for x in expected] == sorted(
        data_block.index(x) for x in expected)


def test_classroom_bigscreen_menu_matches_admin_nav():
    """课堂大屏隐藏顶部导航后使用独立「全站菜单」，必须与 base.html 同步。"""
    base_src = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    classroom_src = (ROOT / 'templates' / 'admin_classroom.html').read_text(
        encoding='utf-8')
    menu = classroom_src[classroom_src.index('<!-- 管理员设置栏'):
                         classroom_src.index('<!-- 设置模态框 -->')]
    assert '学生管理' not in menu
    assert _admin_hrefs(classroom_src, admin_only=False) == _admin_hrefs(base_src)


def test_classroom_bigscreen_renders_synced_menu():
    """渲染真实大屏页，确认菜单数据来源（含 recent_exams）可用。"""
    from app import create_app

    app = create_app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['admin_name'] = '导航回归'
        sess['csrf_token'] = 't'
    resp = client.get('/admin/classroom')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    menu = html[html.index('全站菜单'):html.index('id="settingsModal"')]
    for href in ('/admin/dashboard', '/admin/tools/import-python-fill', '/admin/attendance',
                 '/admin/online_students', '/admin/student-drive',
                 '/admin/students', '/admin/class_schedule'):
        assert href in menu
    assert '学生管理' not in menu


def test_spa_admin_nav_is_regrouped():
    src = (ROOT / 'frontend' / 'components' / 'AppHeader.js').read_text(
        encoding='utf-8')
    for label in ('考试与练习', '班级与考勤', '教学资源', '课堂工具', '数据与审计', '系统'):
        assert label in src
    assert '/admin/attendance' in src and '/admin/student-drive' in src
    assert '在线学生' in src and '学生信息' in src
