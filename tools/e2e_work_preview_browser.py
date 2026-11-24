# -*- coding: utf-8 -*-
"""教师作品预览/评价页内嵌预览浏览器 E2E（2026-11-02）。

验证：
1. 作品列表“预览”打开的预览页，“返回作品列表”能回到作品页；
2. 评价页作品文件自动内嵌在“作品内容”框内，不新开标签页；
3. 内嵌预览支持放大/缩小/重置；
4. 评价来源的预览页“返回评价页”能回到评价页。
运行：venv/Scripts/python.exe -X utf8 tools/e2e_work_preview_browser.py
"""
import io
import os
import shutil
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_work_preview')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-work-preview'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (Class, LearningActivity, Resource, Student,  # noqa: E402
                        StudentWork, Teacher, teacher_class)

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__wp_cls_{SFX}'
TEACHER_NAME = f'__wp_t_{SFX}'
STUDENT_NUMBER = f'__wp_s_{SFX}'
PASSWORD = 'WpPass123'
DIR = f'__wp_dir_{SFX}'
DIR_PATH = os.path.join('static', 'uploads', DIR)
PORT = 5017
BASE = f'http://127.0.0.1:{PORT}'
app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
FAILED = []
IDS = {}


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))


def cleanup():
    with app.app_context():
        if IDS.get('work'):
            StudentWork.query.filter_by(id=IDS['work']).delete(
                synchronize_session=False)
        if IDS.get('act'):
            LearningActivity.query.filter_by(id=IDS['act']).delete(
                synchronize_session=False)
        if IDS.get('res'):
            Resource.query.filter_by(id=IDS['res']).delete(
                synchronize_session=False)
        if IDS.get('teacher'):
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == IDS['teacher']))
            Teacher.query.filter_by(id=IDS['teacher']).delete(
                synchronize_session=False)
        if IDS.get('stu'):
            Student.query.filter_by(id=IDS['stu']).delete(
                synchronize_session=False)
        if IDS.get('cls'):
            Class.query.filter_by(id=IDS['cls']).delete(
                synchronize_session=False)
        db.session.commit()
    shutil.rmtree(DIR_PATH, ignore_errors=True)


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    teacher = Teacher(username=TEACHER_NAME, display_name='预览E2E教师')
    teacher.set_password(PASSWORD)
    teacher.classes.append(cls)
    stu = Student(name='预览E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    db.session.add_all([cls, teacher, stu])
    db.session.flush()
    stu.class_id = cls.id
    os.makedirs(DIR_PATH, exist_ok=True)
    with open(os.path.join(DIR_PATH, 'answer.txt'), 'w', encoding='utf-8') as f:
        f.write('学生作品预览内容 E2E')
    res = Resource(title=f'__wp_res_{SFX}', url='', show_in_student=True,
                   show_in_classroom=True, creator_type='teacher',
                   creator_teacher_id=teacher.id, creator_name='预览E2E教师')
    db.session.add(res)
    db.session.flush()
    act = LearningActivity(resource_id=res.id, title=f'__wp_act_{SFX}',
                           require_upload=True, is_active=True)
    db.session.add(act)
    db.session.flush()
    work = StudentWork(activity_id=act.id, student_id=stu.id, status='submitted',
                       original_filename='answer.txt',
                       file_path=f'{DIR}/answer.txt', file_size=32)
    db.session.add(work)
    db.session.commit()
    IDS.update(cls=cls.id, teacher=teacher.id, stu=stu.id, res=res.id,
               act=act.id, work=work.id)

threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=8), daemon=True).start()
time.sleep(2.0)
os.makedirs('data/e2e_work_preview', exist_ok=True)

from playwright.sync_api import sync_playwright  # noqa: E402

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(base_url=BASE,
                                  viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.goto('/teacher/login')
        page.fill('input[name="username"]', TEACHER_NAME)
        # 只读默认勾选时密码框隐藏：先退出只读再填密码（e2e 库可能已配置访问码）
        mode = page.locator('#readonlyMode')
        if mode.count() and mode.is_enabled() and mode.is_checked():
            mode.uncheck()
        page.fill('input[name="password"]', PASSWORD)
        page.locator('form').filter(
            has=page.locator('input[name="username"]')).locator(
            'button[type="submit"]').click()
        page.wait_for_url('**/teacher/*', timeout=15000)

        # 1) 作品列表预览 → 返回作品页
        page.goto(f'/teacher/works/activity/{IDS["act"]}')
        page.wait_for_selector('table')
        with page.expect_popup() as pop:
            page.locator('a:has-text("预览")').first.click()
        pp = pop.value
        pp.wait_for_load_state('domcontentloaded', timeout=15000)
        show('作品预览页有“返回作品列表”', '返回作品列表' in pp.content())
        pp.locator('a:has-text("返回作品列表")').click()
        pp.wait_for_url(f'**/teacher/works/activity/{IDS["act"]}*', timeout=10000)
        show('作品预览返回作品页',
             f'/teacher/works/activity/{IDS["act"]}' in pp.url, pp.url)
        pp.close()

        # 2) 评价页自动内嵌预览
        page.goto(f'/teacher/works/evaluate/{IDS["work"]}')
        page.wait_for_selector('#workPreviewFrame', timeout=15000)
        src = page.locator('#workPreviewFrame').get_attribute('src') or ''
        show('评价页自动加载内嵌预览', 'embed=1' in src and 'source=evaluate' in src,
             src[:100])
        frame = page.frame_locator('#workPreviewFrame')
        # .txt 走 JitViewer 文本渲染（不是原生 #textPreview），按正文等待
        frame.locator('body').get_by_text('学生作品预览内容 E2E').wait_for(
            timeout=15000)
        preview_text = frame.locator('body').inner_text()
        show('内嵌预览内容生效', '学生作品预览内容 E2E' in preview_text,
             preview_text[:50])

        # 3) 放大/缩小/重置
        text_node = frame.get_by_text('学生作品预览内容 E2E').first
        text_before = text_node.bounding_box()
        page.locator('#workPreviewZoomIn').click()
        page.locator('#workPreviewZoomIn').click()
        show('预览放大到 120%',
             page.locator('#workPreviewZoomLabel').inner_text() == '120%',
             page.locator('#workPreviewZoomLabel').inner_text())
        inner_zoom = frame.locator('html').evaluate("e => e.style.zoom")
        show('缩放作用到预览文档', inner_zoom == '1.2', inner_zoom)
        text_after = text_node.bounding_box()
        show('预览放大改变内容尺寸',
             bool(text_before and text_after and
                  text_after['height'] > text_before['height'] * 1.1),
             f'{text_before["height"] if text_before else 0:.0f} → '
             f'{text_after["height"] if text_after else 0:.0f}px')
        page.locator('#workPreviewZoomOut').click()
        show('预览缩小到 110%',
             page.locator('#workPreviewZoomLabel').inner_text() == '110%',
             page.locator('#workPreviewZoomLabel').inner_text())
        page.locator('#workPreviewZoomReset').click()
        show('预览重置到 100%',
             page.locator('#workPreviewZoomLabel').inner_text() == '100%',
             page.locator('#workPreviewZoomLabel').inner_text())

        # 4) 评价来源预览页返回评价页
        page.goto(f'/works/file/{IDS["work"]}/preview?source=evaluate')
        page.wait_for_selector('text=返回评价页', timeout=15000)
        page.locator('a:has-text("返回评价页")').click()
        page.wait_for_url(f'**/teacher/works/evaluate/{IDS["work"]}', timeout=10000)
        show('预览页返回评价页',
             f'/teacher/works/evaluate/{IDS["work"]}' in page.url, page.url)

        page.screenshot(path='data/e2e_work_preview/evaluate_inline.png',
                        full_page=True)
        browser.close()
finally:
    cleanup()

print(f'—— 结果: {len(FAILED) == 0 and "全部通过" or "失败 " + ", ".join(FAILED)} ——')
sys.exit(0 if not FAILED else 1)
