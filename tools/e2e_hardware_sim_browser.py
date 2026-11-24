# -*- coding: utf-8 -*-
"""硬件仿真宿主页真实浏览器 E2E（Playwright + Edge 无头）。

链路：隔离库建班级/学生/激活课堂 → 学生登录 → /hardware-sim
→ 两个标签 iframe 懒加载 → 掌控板/ESP32-S3 标题与中文
→ ?tab= 深链、新窗口链接、全高布局、uid 存储隔离、CSP 无违规。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_hardware_sim_browser.py
环境：隔离库 itstudy_e2e、端口 5012、独立缓存；测后清理。
"""
import io
import os
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_hardware_sim')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-hardware-sim'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import AttendanceRecord, Class, ClassroomSession, Student  # noqa: E402

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__hw_e2e_class_{SFX}'
STUDENT_NUMBER = f'__hw_e2e_{SFX}'
PASSWORD = 'HwE2ePass123'
PORT = 5012
BASE = f'http://127.0.0.1:{PORT}'

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)

FAILED = []


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))


def cleanup():
    """清掉本次与历史遗留的 __hw_e2e_* 测试数据。"""
    with app.app_context():
        for stu in Student.query.filter(
                Student.student_number.like('__hw_e2e_%')).all():
            AttendanceRecord.query.filter_by(student_id=stu.id).delete(
                synchronize_session=False)
            db.session.delete(stu)
        for cls in Class.query.filter(
                Class.name.like('__hw_e2e_class_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            db.session.delete(cls)
        db.session.commit()


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    stu = Student(name='硬件仿真E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    db.session.commit()
    STUDENT_ID = stu.id
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

from waitress import serve  # noqa: E402

threading.Thread(target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
                 daemon=True).start()
time.sleep(1.5)

from playwright.sync_api import sync_playwright  # noqa: E402

SHOT = os.path.join('data', 'e2e_hardware_sim')
os.makedirs(SHOT, exist_ok=True)
page_errors = []
csp_errors = []

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                                  base_url=BASE)
        page = ctx.new_page()
        page.on('pageerror', lambda e: page_errors.append(str(e)))

        def on_console(msg):
            text = msg.text or ''
            if msg.type == 'error' and ('Content Security Policy' in text or
                                        'Refused to' in text):
                csp_errors.append(text[:300])

        page.on('console', on_console)

        # 登录（学生登录需要 active 班级）
        page.goto('/')
        page.fill('input[name="student_number"]', STUDENT_NUMBER)
        page.fill('input[name="password"]', PASSWORD)
        page.locator('form').filter(
            has=page.locator('input[name="student_number"]')
        ).locator('button[type="submit"]').click()
        page.wait_for_url('**/study*', timeout=15000)
        show('学生登录并进入学习资源', True, page.url)

        # 宿主页
        page.goto('/hardware-sim')
        page.wait_for_selector('.hw-sim-page', timeout=10000)
        show('硬件仿真页面加载', page.title().startswith('硬件仿真'), page.title())
        show('两个标签', page.locator('.hw-sim-tab').count() == 2,
             f'实际 {page.locator(".hw-sim-tab").count()}')
        show('默认图形编程标签', 'active' in (page.locator('#hwTabMmake').get_attribute('class') or ''))

        # mmake iframe
        page.wait_for_function(
            "() => { const f=document.getElementById('hwFrameMmake');"
            " return f && f.contentDocument && f.contentDocument.readyState==='complete'; }",
            timeout=30000)
        mm_title = page.evaluate(
            "document.getElementById('hwFrameMmake').contentDocument.title")
        show('掌控板 iframe 加载', '掌控' in mm_title, mm_title)
        mm_h = page.evaluate(
            "document.getElementById('hwFrameMmake').clientHeight")
        show('iframe 高度铺满', mm_h > 420, f'{mm_h}px')
        no_scroll = page.evaluate(
            "document.documentElement.scrollHeight <= window.innerHeight + 2")
        show('宿主页无双重滚动条', no_scroll)
        keys = page.evaluate(
            "Object.keys(document.getElementById('hwFrameMmake').contentWindow.localStorage)")
        own_prefix = f'u_student_{STUDENT_ID}__'
        show('掌控板 localStorage 带账号前缀',
             any(k.startswith(own_prefix) for k in keys),
             f'前缀 {own_prefix}，键数 {len(keys)}')

        # 切 ESP32
        page.click('#hwTabEsp32')
        page.wait_for_function(
            "() => { const f=document.getElementById('hwFrameEsp32');"
            " return f && f.contentDocument &&"
            " f.contentDocument.title.includes('工作台'); }",
            timeout=60000)
        esp_title = page.evaluate(
            "document.getElementById('hwFrameEsp32').contentDocument.title")
        show('ESP32-S3 iframe 加载且中文', '工作台' in esp_title, esp_title)
        page.evaluate(
            "document.getElementById('hwFrameEsp32').contentWindow.location.hash = '#/lessons/02'")
        page.wait_for_function(
            "() => { const w=document.getElementById('hwFrameEsp32').contentWindow;"
            " return w && Object.keys(w.localStorage).some(k => k.endsWith('__esp-lesson')); }",
            timeout=15000)
        esp_keys = page.evaluate(
            "Object.keys(document.getElementById('hwFrameEsp32').contentWindow.localStorage)")
        show('ESP32 localStorage 带账号前缀',
             any(k == f'u_student_{STUDENT_ID}__esp-lesson' for k in esp_keys),
             f'键数 {len(esp_keys)}')
        href = page.locator('#hwSimOpen').get_attribute('href') or ''
        show('新窗口链接指向 ESP32 且带 uid',
             'hardware-sim/esp32-s3/index.html' in href and
             f'uid=student_{STUDENT_ID}' in href, href[-90:])

        # ?tab= 深链
        page.goto('/hardware-sim?tab=esp32')
        page.wait_for_selector('.hw-sim-page', timeout=10000)
        show('?tab=esp32 深链', 'active' in (page.locator('#hwTabEsp32').get_attribute('class') or ''))

        # 教学提示 / 沉浸模式 / 键盘
        page.click('#hwSimTipsBtn')
        show('使用提示展开', page.locator('#hwSimTips').is_visible())
        page.click('#hwSimTipsBtn')
        show('使用提示收起', not page.locator('#hwSimTips').is_visible())
        page.click('#hwSimImmersiveBtn')
        show('沉浸模式隐藏站点导航', not page.locator('nav.navbar').is_visible())
        show('沉浸模式 aria-pressed',
             page.locator('#hwSimImmersiveBtn').get_attribute('aria-pressed') == 'true')
        page.keyboard.press('Escape')
        show('Esc 退出沉浸', page.locator('nav.navbar').is_visible())
        page.locator('#hwTabEsp32').focus()
        page.keyboard.press('ArrowLeft')
        show('键盘左箭头切换标签',
             'active' in (page.locator('#hwTabMmake').get_attribute('class') or ''))

        # 移动端布局
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(500)
        show('移动端无横向溢出',
             page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"))
        show('移动端标签可见', page.locator('.hw-sim-tabs').is_visible())
        page.screenshot(path=os.path.join(SHOT, 'hardware_sim_mobile.png'))
        page.set_viewport_size({'width': 1600, 'height': 900})
        page.wait_for_timeout(300)

        # uid 存储隔离：同一浏览器上下文里的两个 uid 互不可见
        iso = ctx.new_page()
        iso.goto('/static/hardware-sim/mmake/index.html?uid=e2e_a')
        iso.wait_for_function('() => window.ZKB && window.ZKB.Store', timeout=15000)
        iso.evaluate("window.ZKB.Store.setLocal('iso_marker', 'A')")
        iso.goto('/static/hardware-sim/mmake/index.html?uid=e2e_b')
        iso.wait_for_function('() => window.ZKB && window.ZKB.Store', timeout=15000)
        b_value = iso.evaluate("window.ZKB.Store.getLocal('iso_marker')")
        show('uid=e2e_b 看不到 e2e_a 的数据', b_value is None, str(b_value))
        iso.goto('/static/hardware-sim/mmake/index.html?uid=e2e_a')
        iso.wait_for_function('() => window.ZKB && window.ZKB.Store', timeout=15000)
        a_value = iso.evaluate("window.ZKB.Store.getLocal('iso_marker')")
        show('uid=e2e_a 数据仍在', a_value == 'A', str(a_value))

        page.screenshot(path=os.path.join(SHOT, 'hardware_sim.png'))
        browser.close()
finally:
    cleanup()

show('无 CSP 违规', not csp_errors, '; '.join(csp_errors[:3]))
show('无页面 JS 异常', not page_errors, '; '.join(page_errors[:3]))
print(f'\n结果：{len(FAILED) == 0 and "全部通过" or "失败 " + ", ".join(FAILED)}')
sys.exit(0 if not FAILED else 1)
