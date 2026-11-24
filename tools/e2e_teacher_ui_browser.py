# -*- coding: utf-8 -*-
"""教师登录/AI/账号页真实浏览器 E2E（Playwright + Edge 无头）。

覆盖：
  1. 教师登录页默认勾选只读模式；只读访问码登录成功；
  2. 只读教师进入课堂页后 AI 助手悬浮按钮存在（教师 AI 开关开启）；
  3. 管理员教师账号页：复选框下拉、分配弹窗预选与提交、改密弹窗提交；
  4. 管理员 AI 配置页：教师端开关可见并能保存。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_teacher_ui_browser.py
环境：隔离库 itstudy_e2e、端口 5031、缓存独立；测后清理并还原配置。
"""
import io
import os
import sys
import threading
import time

from werkzeug.security import generate_password_hash

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_teacher_ui')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-teacher-ui-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AdminAccount, AIConfig, Class, ClassSchedule,  # noqa: E402
                        ClassroomSession, ClassroomSetting, Schedule, Subject,
                        SystemConfig, Teacher, TeacherAIConfig, teacher_class,
                        teacher_subject)
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY  # noqa: E402
from app.utils import invalidate_lookup_cache  # noqa: E402

PORT = 5031
BASE = f'http://127.0.0.1:{PORT}'
ADMIN = 'tui_admin'
TEACHER = 'tui_teacher'
CLASS_NAME = 'TUI测试班'
SUBJECT_NAME = 'TUI测试学科'
READONLY_CODE = 'TuiReadonly123'
SCHEDULE_PERIOD = 'TUI测试节次'
FAILED = []
app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name} {detail}')


def _cleanup():
    with app.app_context():
        tid = db.session.query(Teacher.id).filter_by(username=TEACHER).scalar()
        if tid:
            TeacherAIConfig.query.filter_by(teacher_id=tid).delete(
                synchronize_session=False)
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id == tid))
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == tid))
            Teacher.query.filter_by(id=tid).delete(synchronize_session=False)
        cid = db.session.query(Class.id).filter_by(name=CLASS_NAME).scalar()
        ClassSchedule.query.filter_by(class_name=CLASS_NAME).delete(
            synchronize_session=False)
        if cid:
            # 教师设置大屏会创建 ClassroomSession；必须先删会话再删班级。
            # 同时解除全局 ClassroomSetting 对测试班级的引用。
            ClassroomSession.query.filter_by(class_id=cid).delete(
                synchronize_session=False)
            ClassroomSetting.query.filter_by(active_class_id=cid).update(
                {ClassroomSetting.active_class_id: None}, synchronize_session=False)
            Class.query.filter_by(id=cid).delete(synchronize_session=False)
        Schedule.query.filter_by(period_name=SCHEDULE_PERIOD).delete(
            synchronize_session=False)
        Subject.query.filter_by(name=SUBJECT_NAME).delete(synchronize_session=False)
        AdminAccount.query.filter_by(username=ADMIN).delete(synchronize_session=False)
        db.session.commit()
        invalidate_lookup_cache('schedules')


_cleanup()
with app.app_context():
    subj = Subject(name=SUBJECT_NAME, sort_order=910)
    cls = Class(name=CLASS_NAME)
    teacher = Teacher(username=TEACHER, display_name='TUI教师', grade='高一')
    teacher.set_password('TuiPass123')
    teacher.subjects = [subj]
    teacher.classes = [cls]
    admin = AdminAccount(username=ADMIN, display_name='TUI管理员')
    admin.set_password('TuiAdmin123')
    db.session.add_all([subj, cls, teacher, admin])
    db.session.add_all([
        Schedule(period_name=SCHEDULE_PERIOD, start_time='08:00',
                 end_time='08:45', sort_order=1, is_active=True),
        ClassSchedule(weekday=1, period_number=1, class_name=CLASS_NAME),
    ])

    saved_code = SystemConfig.get(TEACHER_READONLY_CODE_KEY) or ''
    SystemConfig.set(TEACHER_READONLY_CODE_KEY,
                     generate_password_hash(READONLY_CODE, method='pbkdf2:sha256'))

    cfg = AIConfig.query.first()
    cfg_created = cfg is None
    if cfg_created:
        cfg = AIConfig()
        db.session.add(cfg)
    saved_cfg = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model, cfg._api_key,
                 cfg.teacher_enabled, cfg.teacher_page_context_default)
    cfg.enabled, cfg.config_mode = True, 'admin'
    cfg.api_url, cfg.model = 'http://127.0.0.1:9/v1', 'tui-model'
    cfg.api_key = 'sk-tui-test'
    cfg.teacher_enabled = True
    cfg.teacher_page_context_default = True
    db.session.commit()
    invalidate_lookup_cache('schedules')
    subj_id = subj.id
    class_id = cls.id

    from waitress import serve
    threading.Thread(
        target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
        daemon=True).start()
    time.sleep(1.5)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)

            # 1. 教师登录默认只读 + 只读登录成功
            ctx_teacher = browser.new_context(base_url=BASE)
            page = ctx_teacher.new_page()
            page.goto('/teacher/login')
            show('T1 教师登录默认勾选只读模式', page.locator('#readonlyMode').is_checked())
            show('T2 只读模式显示访问码并隐藏密码',
                 page.locator('#readonlyCodeGroup').is_visible()
                 and not page.locator('#passwordGroup').is_visible())
            page.fill('input[name="username"]', TEACHER)
            page.fill('input[name="readonly_code"]', READONLY_CODE)
            page.click('button[type="submit"]')
            page.wait_for_url('**/study?mode=classroom', timeout=15000)
            show('T3 只读教师登录进入课堂页', True, page.url)
            fab_ok = False
            for _ in range(30):
                if page.locator('#aiFab').count() == 1:
                    fab_ok = True
                    break
                page.wait_for_timeout(200)
            show('T4 只读教师可使用 AI 助手悬浮按钮', fab_ok)

            page.goto('/teacher/schedule')
            schedule_html = page.content()
            show('T4b 只读教师可查看作息与课程表',
                 SCHEDULE_PERIOD in schedule_html and CLASS_NAME in schedule_html)

            # 1b. 只读教师查看并设置课堂大屏（仅本人任课班级）
            page.goto('/admin/classroom')
            page.wait_for_selector('#settingsModal', state='attached', timeout=10000)
            show('T5 只读教师可打开课堂大屏',
                 page.locator('.admin-bar button:has-text("设置")').count() == 1)
            show('T6 大屏不显示管理员全站菜单',
                 page.locator('.admin-bar button:has-text("全站菜单")').count() == 0)
            page.click('.admin-bar button:has-text("设置")')
            page.wait_for_selector('#settingsModal.show', timeout=5000)
            page.select_option('#settingsModal select[name="active_class_id"]',
                              str(class_id))
            page.fill('#settingsModal input[name="display_message"]', '只读教师设置')
            page.locator('#settingsModal button[type="submit"]').click()
            page.wait_for_url(f'**/admin/classroom?class_id={class_id}', timeout=15000)
            show('T7 只读教师保存本班课堂设置',
                 '只读教师设置' in page.locator('#messageDisplay').inner_text())

            # 1c. 编辑模式可自行配置 API，保存后 AI 图标仍可用
            ctx_edit = browser.new_context(base_url=BASE)
            epage = ctx_edit.new_page()
            epage.goto('/teacher/login')
            epage.uncheck('#readonlyMode')
            epage.fill('input[name="username"]', TEACHER)
            epage.fill('input[name="password"]', 'TuiPass123')
            epage.click('button[type="submit"]')
            epage.wait_for_url('**/teacher/*', timeout=15000)
            edit_fab = False
            for _ in range(30):
                if epage.locator('#aiFab').count() == 1:
                    edit_fab = True
                    break
                epage.wait_for_timeout(200)
            show('T7b 编辑模式显示 AI 助手图标', edit_fab)
            epage.goto('/teacher/resource-library')
            show('T7e 教师导航含作息时间表入口',
                 epage.locator('a[href="/teacher/schedule"]').count() >= 1)
            epage.goto('/teacher/schedule')
            schedule_edit_html = epage.content()
            show('T7f 编辑模式可查看作息与课程表',
                 SCHEDULE_PERIOD in schedule_edit_html and CLASS_NAME in schedule_edit_html)
            epage.goto('/teacher/ai_config')
            epage.fill('#apiUrl', 'https://api.deepseek.com/v1')
            epage.fill('#apiKey', 'sk-e2e-teacher')
            epage.evaluate("""() => {
                var s = document.getElementById('modelSelect');
                var o = document.createElement('option');
                o.value = 'e2e-teacher-model'; o.text = 'e2e-teacher-model';
                s.appendChild(o); s.value = 'e2e-teacher-model';
            }""")
            epage.click('button:has-text("保存个人配置")')
            saved_msg = False
            for _ in range(25):
                if '保存成功' in epage.locator('#saveMsg').inner_text():
                    saved_msg = True
                    break
                epage.wait_for_timeout(200)
            show('T7c 编辑模式可保存个人 API 配置', saved_msg)
            epage.goto('/study?mode=classroom')
            self_fab = False
            for _ in range(30):
                if epage.locator('#aiFab').count() == 1:
                    self_fab = True
                    break
                epage.wait_for_timeout(200)
            show('T7d 自配 API 后 AI 图标可用', self_fab)

            # 2. 管理员教师账号页：下拉复选、弹窗分配/改密
            ctx_admin = browser.new_context(base_url=BASE)
            apage = ctx_admin.new_page()
            apage.goto('/admin/login')
            apage.fill('input[name="username"]', ADMIN)
            apage.fill('input[name="password"]', 'TuiAdmin123')
            apage.click('button[type="submit"]')
            apage.wait_for_url('**/admin/resources', timeout=15000)

            apage.goto('/admin/teacher_account')
            show('T8 教师账号页加载复选框下拉',
                 apage.locator('[data-field="create-subjects"]').count() == 1)
            apage.locator('[data-field="create-subjects"] button').click()
            apage.locator(
                f'[data-field="create-subjects"] input[value="{subj_id}"]').check()
            label = apage.locator('[data-field="create-subjects"] .cb-label').inner_text()
            show('T9 学科复选后下拉显示已选学科', SUBJECT_NAME in label, label)
            apage.keyboard.press('Escape')

            apage.locator('.assign-btn').first.click()
            apage.wait_for_selector('#assignModal.show', timeout=5000)
            preselected = apage.locator(
                f'#assignModal input[name="subject_ids"][value="{subj_id}"]').is_checked()
            show('T10 分配弹窗预选当前学科', preselected)
            apage.locator('#assignModal button[type="submit"]').click()
            apage.wait_for_load_state('networkidle')
            show('T11 分配弹窗提交成功', '教师学科/年级/班级已更新' in apage.content())

            apage.locator('.password-btn').first.click()
            apage.wait_for_selector('#passwordModal.show', timeout=5000)
            apage.fill('#passwordModal input[name="password"]', 'TuiNewPass123')
            apage.locator('#passwordModal button[type="submit"]').click()
            apage.wait_for_load_state('networkidle')
            show('T12 改密弹窗提交成功', '教师密码已更新' in apage.content())

            # 3. AI 配置页教师端开关
            apage.goto('/admin/ai_config')
            show('T13 AI 配置页包含教师端开关',
                 apage.locator('#teacherEnabledSwitch').count() == 1
                 and apage.locator('#teacherPageContextSwitch').count() == 1)
            apage.uncheck('#teacherEnabledSwitch')
            apage.click('button:has-text("保存配置")')
            saved = False
            for _ in range(25):
                if '保存成功' in apage.locator('#saveMsg').inner_text():
                    saved = True
                    break
                apage.wait_for_timeout(200)
            show('T14 教师端 AI 开关可保存', saved)

            browser.close()
    finally:
        with app.app_context():
            cfg = AIConfig.query.first()
            if cfg is not None:
                if cfg_created:
                    db.session.delete(cfg)
                else:
                    (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model, cfg._api_key,
                     cfg.teacher_enabled, cfg.teacher_page_context_default) = saved_cfg
            SystemConfig.set(TEACHER_READONLY_CODE_KEY, saved_code)
            db.session.commit()
        _cleanup()

print()
print(f'══ 教师登录/AI/账号页 E2E：{"全部通过" if not FAILED else f"{len(FAILED)} 项失败：{FAILED}"} ══')
sys.exit(1 if FAILED else 0)
