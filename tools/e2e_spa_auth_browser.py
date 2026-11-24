# -*- coding: utf-8 -*-
"""SPA 登录 / 导航 / CSRF 真实浏览器 E2E（Playwright + Edge 无头）。

回归对象（2026-10-19）：
  - SPA 根组件必须挂载 AppHeader（登录后可见导航与“退出”）；
  - CSRF 头必须单值（axios 内建 XSRF 与 XHR 补丁叠加时变成
    "token, token"，服务端校验恒失败 → 登录 403）；
  - resource-loader 不得在 CSS 加载成功后移除 <link>（FontAwesome 图标）。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_spa_auth_browser.py
环境：隔离库 itstudy_e2e、端口 5021、缓存独立；测后清理。
"""
import io
import os
import secrets
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_spa_auth')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-spa-auth-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import AdminAccount  # noqa: E402

PORT = 5021
ADMIN_USER = 'spa_e2e_admin'
ADMIN_PASS = secrets.token_urlsafe(12)
app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
FAILED = []


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name} {detail}')


def _cleanup():
    with app.app_context():
        AdminAccount.query.filter_by(username=ADMIN_USER).delete()
        db.session.commit()


def main():
    _cleanup()
    with app.app_context():
        acct = AdminAccount(username=ADMIN_USER, display_name='SPA E2E')
        acct.set_password(ADMIN_PASS)
        db.session.add(acct)
        db.session.commit()

    from waitress import serve
    threading.Thread(
        target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
        daemon=True).start()
    time.sleep(1.5)

    from playwright.sync_api import sync_playwright
    console_errors = []
    csrf_headers = []
    bad_responses = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge')
            page = browser.new_page()
            page.on('console', lambda m: console_errors.append(m.text)
                    if m.type == 'error' else None)
            page.on('request', lambda r: csrf_headers.append(
                r.headers.get('x-csrftoken', ''))
                    if 'admin-login' in r.url else None)
            page.on('response', lambda r: bad_responses.append((r.status, r.url))
                    if r.status >= 400 else None)

            page.goto(f'http://127.0.0.1:{PORT}/app/#/admin/login',
                      wait_until='networkidle')
            page.fill('input[type=text]', ADMIN_USER)
            page.fill('input[type=password]', ADMIN_PASS)
            page.click('button[type=submit]')
            page.wait_for_url('**#/admin/exams', timeout=15000)
            page.wait_for_timeout(1200)

            header = page.locator('header').first
            show('S1 登录后顶部导航可见', header.is_visible())
            show('S2 导航含退出按钮',
                 page.locator('header button', has_text='退出').count() == 1)
            show('S3 FontAwesome 样式仍挂载',
                 page.evaluate("!!document.querySelector('link[href*=fontawesome]')"))
            single_csrf = bool(csrf_headers) and ',' not in csrf_headers[0]
            show('S4 CSRF 头为单值', single_csrf,
                 f'值={csrf_headers[0][:12] if csrf_headers else "(无)"}')

            page.locator('header button', has_text='退出').click()
            page.wait_for_url('**#/', timeout=10000)
            show('S5 退出后回到登录页', page.locator('header').count() == 0
                 or not page.locator('header').first.is_visible())

            js_errors = [e for e in console_errors
                         if 'Failed to load resource' not in e]
            bad = [x for x in bad_responses if 'favicon' not in x[1]]
            show('S6 页面 JS/资源错误为 0', not js_errors and not bad,
                 str(js_errors[:3]) + ' 非 2xx: ' + str(bad[:5]))
            browser.close()
    finally:
        _cleanup()

    print()
    if FAILED:
        print(f'══ SPA 登录/导航 E2E：{len(FAILED)} 项失败：{FAILED} ══')
        return 1
    print('══ SPA 登录/导航 E2E：6/6 通过 ══')
    return 0


if __name__ == '__main__':
    sys.exit(main())
