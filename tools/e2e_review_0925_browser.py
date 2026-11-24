# -*- coding: utf-8 -*-
"""2026-09-25 审查修复的真实浏览器验证（Playwright + Edge 无头）

T1 资源分块上传：页面内原生 XHR 不手工带 token，靠全局补丁注入 CSRF 头
   （修复前补丁先设头后 open → 异常被吞 → 逐块 403）
T2 学生网盘管理页：加载无 JS 错误；「待清理清单」按钮能弹出模态框
   （修复前解析期 new bootstrap.Modal 抛 ReferenceError，三个按钮全无响应）
T3 预览页：name 参数构造属性注入不得执行脚本（修复前 alt="…" 可被闭合）

运行：venv/Scripts/python.exe -X utf8 tools/e2e_review_0925_browser.py
环境：隔离库 itstudy_e2e、端口 5015、缓存独立；测后清理。任一失败退出码 1。
"""
import io
import os
import shutil
import sys
import threading
import time
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_0925')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-0925-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from sqlalchemy import text as _text  # noqa: E402

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
UP = os.path.join(os.getcwd(), 'static', 'uploads')
COURSE_TITLE = 'E0925课件'
PREVIEW_DIR = os.path.join(UP, 'E0925_preview')
ADMIN, PWD = 'e0925_admin', 'E0925Admin!'
# 故意用无效图片内容：注入的是 onerror，图片必须加载失败才会触发
# （用有效 PNG 时修复前的漏洞也测不出来）
BAD_IMAGE = b'not a png e0925'


def _cleanup():
    with app.app_context():
        db.session.execute(_text('DELETE FROM admin_account WHERE username=:u'), {'u': ADMIN})
        db.session.commit()
    shutil.rmtree(os.path.join(UP, COURSE_TITLE), ignore_errors=True)
    shutil.rmtree(PREVIEW_DIR, ignore_errors=True)
    shutil.rmtree(os.path.join(os.getcwd(), 'static', 'chunks', 'e0925up'), ignore_errors=True)


_cleanup()
from app.models import AdminAccount  # noqa: E402
with app.app_context():
    a = AdminAccount(username=ADMIN, display_name='E0925')
    a.set_password(PWD)
    db.session.add(a)
    db.session.commit()
os.makedirs(PREVIEW_DIR, exist_ok=True)
with open(os.path.join(PREVIEW_DIR, 'pic.png'), 'wb') as f:
    f.write(BAD_IMAGE)

PORT = 5015
BASE = f'http://127.0.0.1:{PORT}'
threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=8), daemon=True).start()
time.sleep(2.5)

from playwright.sync_api import sync_playwright  # noqa: E402

results, page_errors = [], []


def check(name, cond, extra=''):
    results.append(bool(cond))
    print(f'[{"PASS" if cond else "FAIL"}] {name}' + (f' | {extra}' if extra else ''))


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(base_url=BASE, viewport={'width': 1400, 'height': 900})
        page = ctx.new_page()
        page.on('pageerror', lambda e: page_errors.append((page.url, str(e))))
        page.on('dialog', lambda d: d.dismiss())

        page.goto('/admin/login')
        page.fill('input[name="username"]', ADMIN)
        page.fill('input[name="password"]', PWD)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        check('T0 管理员登录', 'login' not in page.url, page.url[-30:])

        # ── T1：原生 XHR 分块上传，不手工带 token ──
        page.goto('/admin/resources/upload_page')
        page.wait_for_load_state('networkidle')
        res = page.evaluate("""(title) => new Promise((resolve) => {
            const fd = new FormData();
            fd.append('chunk', new Blob(['hello e0925']), 'blob');
            fd.append('chunk_index', '0'); fd.append('total_chunks', '1');
            fd.append('filename', 'e0925.txt'); fd.append('upload_id', 'e0925up');
            fd.append('title', title); fd.append('subfolder', '');
            const x = new XMLHttpRequest();
            x.open('POST', '/admin/resources/chunk_upload', true);
            x.onload = () => resolve({status: x.status, body: x.responseText.slice(0, 200)});
            x.onerror = () => resolve({status: -1, body: ''});
            x.send(fd);
        })""", COURSE_TITLE)
        check('T1 原生 XHR 分块上传（全局补丁注入 CSRF）',
              res['status'] == 200 and '"success": true' in res['body'].replace('":true', '": true'),
              f"HTTP {res['status']} {res['body'][:80]}")
        check('T1b 合并文件已落盘',
              os.path.isfile(os.path.join(UP, COURSE_TITLE, 'e0925.txt')))

        # ── T2：学生网盘管理页清理弹窗 ──
        errs_before = len(page_errors)
        page.goto('/admin/student-drive')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(500)
        new_errs = page_errors[errs_before:]
        check('T2 网盘管理页加载无 JS 错误', not new_errs, str(new_errs[:1]))
        page.click('#cleanupPreviewBtn')
        try:
            page.wait_for_selector('#cleanupPreviewModal.show', timeout=5000)
            shown = True
        except Exception:
            shown = False
        check('T2b 「待清理清单」弹出模态框', shown)

        # ── T3：预览页属性注入 ──
        evil = 'x" onerror="window.__xss=1" data-a=".png'
        page.goto('/study/preview?file=' + quote('/static/uploads/E0925_preview/pic.png')
                  + '&name=' + quote(evil))
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(800)
        xss = page.evaluate('() => window.__xss === 1')
        alt = page.evaluate("() => (document.querySelector('#jitViewerContainer img')||{}).alt")
        check('T3 预览页 name 参数不执行脚本', not xss, f'alt={alt!r}')
        check('T3b alt 按原样显示文件名', alt == evil)

        browser.close()
finally:
    _cleanup()

print('—— 页面 JS 错误 ——')
for u, e in page_errors[:5]:
    print(' ', u[-40:], e[:150])
failed = results.count(False)
print(f'===== 2026-09-25 修复浏览器验证：{len(results) - failed}/{len(results)} 通过 =====')
sys.exit(1 if failed else 0)
