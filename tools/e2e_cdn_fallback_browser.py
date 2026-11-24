# -*- coding: utf-8 -*-
"""CDN 多级回退真实浏览器 E2E（2026-11-17）。

隔离库 itstudy_e2e + Edge：在真实页面 CSP 下验证
本地失败 → 国内镜像成功、国内全失败 → 官方 CDN 成功、
SRI 篡改内容被拦截后继续回退、离线只尝试本地。
镜像内容用与官方 SRI 一致的本地 marked 文件充当，不依赖外网。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_cdn_fallback_browser.py
"""
import io
import os
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_cdn')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-cdn'
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'tools'))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import AttendanceRecord, Class, ClassroomSession, Student  # noqa: E402
from e2e_common import reset_shared_state  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from waitress import create_server  # noqa: E402

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__cdn_e2e_class_{SFX}'
STUDENT_NUMBER = f'__cdn_e2e_{SFX}'
PASSWORD = 'CdnE2ePass123'
PORT = 5024
BASE = f'http://127.0.0.1:{PORT}'
MARKED_LOCAL = os.path.join('static', 'marked', 'marked.min.js')
DOMESTIC = (
    'https://cdn.bootcdn.net/ajax/libs/marked/12.0.2/marked.min.js',
    'https://cdn.staticfile.org/marked/12.0.2/marked.min.js',
    'https://lib.baomitu.com/marked/12.0.2/marked.min.js',
    'https://npm.elemecdn.com/marked@12.0.2/marked.min.js',
)
OFFICIAL = 'https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js'
TAMPERED = b'window.marked = {tampered: true};'

app = create_app()
reset_shared_state(app)
FAILED = []
IDS = {}
SHOT = os.path.join('data', 'e2e_cdn')
REQUESTS = []
CSP_ERRORS = []
CONSOLE = []
CHECKED = []


def check(name, ok, detail=''):
    CHECKED.append(name)
    print(('✓ ' if ok else '✗ ') + name + (f' | {detail}' if detail else ''))
    if not ok:
        FAILED.append(name)


def cleanup():
    with app.app_context():
        for stu in Student.query.filter(
                Student.student_number.like('__cdn_e2e_%')).all():
            AttendanceRecord.query.filter_by(student_id=stu.id).delete(
                synchronize_session=False)
            db.session.delete(stu)
        for cls in Class.query.filter(
                Class.name.like('__cdn_e2e_class_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            db.session.delete(cls)
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    stu = Student(name='CDN回退E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    db.session.commit()
    IDS.update(cls=cls.id, stu=stu.id)
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

server = create_server(app, host='127.0.0.1', port=PORT, threads=8)
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1.5)
os.makedirs(SHOT, exist_ok=True)

with open(MARKED_LOCAL, 'rb') as f:
    MARKED_BYTES = f.read()

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(viewport={'width': 1280, 'height': 800},
                                  base_url=BASE)
        page = ctx.new_page()
        page.on('request', lambda req: REQUESTS.append((req.url, time.monotonic()))
                if 'marked' in req.url else None)
        page.on('console', lambda msg: (
            CSP_ERRORS.append(msg.text) if msg.type == 'error'
            and ('Content Security Policy' in msg.text or 'Refused to' in msg.text)
            else CONSOLE.append(msg.text) if msg.type == 'error' else None))

        page.goto('/')
        page.fill('input[name="student_number"]', STUDENT_NUMBER)
        page.fill('input[name="password"]', PASSWORD)
        page.locator('form').filter(
            has=page.locator('input[name="student_number"]')).locator(
            'button[type="submit"]').click()
        page.wait_for_url('**/study*', timeout=20000)
        page.wait_for_function(
            "() => window.resourceLoader && document.readyState === 'complete'",
            timeout=20000)
        time.sleep(1.0)  # 页面自身的延迟加载结束，避免混入本轮请求计数

        state = {'local': 'fail', 'domestic': 'ok', 'official': 'ok'}
        case = {'name': ''}

        def js_headers():
            return {'content-type': 'application/javascript; charset=utf-8',
                    'access-control-allow-origin': '*'}

        def local_handler(route):
            if state['local'] == 'ok':
                route.fulfill(status=200, content_type='application/javascript',
                              body=MARKED_BYTES)
            else:
                route.fulfill(status=500, body='unavailable')

        def domestic_handler(route):
            if state['domestic'] == 'tampered':
                route.fulfill(status=200, headers=js_headers(), body=TAMPERED)
            elif state['domestic'] == 'ok' and route.request.url.startswith(DOMESTIC[0]):
                route.fulfill(status=200, headers=js_headers(), body=MARKED_BYTES)
            else:
                route.fulfill(status=503, body='unavailable')

        def official_handler(route):
            if state['official'] == 'ok':
                route.fulfill(status=200, headers=js_headers(), body=MARKED_BYTES)
            else:
                route.fulfill(status=503, body='unavailable')

        page.route('**/static/marked/marked.min.js*', local_handler)
        for url in DOMESTIC:
            page.route(url, domestic_handler)
        page.route(OFFICIAL, official_handler)

        def run_case(name, local, domestic, official):
            case['name'] = name
            state.update(local=local, domestic=domestic, official=official)
            REQUESTS.clear()
            CONSOLE.clear()
            result = page.evaluate("""async () => {
              try { delete window.marked; } catch (e) { window.marked = undefined; }
              try {
                const url = await window.resourceLoader.tryLoadByType('marked');
                return {url, parse: typeof (window.marked && window.marked.parse),
                        tampered: !!(window.marked && window.marked.tampered)};
              } catch (e) {
                return {error: String(e), tampered: !!(window.marked && window.marked.tampered)};
              }
            }""")
            urls = [url for url, _ in REQUESTS]
            print(f'[{name}] result={result} requests={len(urls)}')
            return result, urls, list(CONSOLE)

        result, urls, console = run_case('本地失败→国内成功', 'fail', 'ok', 'ok')
        check('本地失败时使用国内镜像', result.get('url') == DOMESTIC[0]
              and result.get('parse') == 'function' and not result.get('tampered'),
              str(result))
        check('先尝试本地再尝试国内', urls and urls[0].startswith(BASE + '/static/marked/')
              and urls[1] == DOMESTIC[0], str(urls))

        result, urls, console = run_case('国内全失败→官方成功', 'fail', 'fail', 'ok')
        check('国内镜像全失败时回退官方 CDN', result.get('url') == OFFICIAL
              and result.get('parse') == 'function', str(result))
        domestic_hits = [u for u in urls if u in DOMESTIC]
        check('按顺序尝试全部国内镜像', domestic_hits == list(DOMESTIC), str(domestic_hits))

        result, urls, console = run_case('国内内容被篡改', 'fail', 'tampered', 'ok')
        integrity = [text for text in console if 'integrity' in text.lower()]
        check('SRI 拒绝被篡改的镜像并继续回退', result.get('url') == OFFICIAL
              and result.get('parse') == 'function' and not result.get('tampered'),
              str(result))
        check('SRI 拦截在浏览器控制台留痕', bool(integrity), '; '.join(integrity[:1]))

        page.evaluate("delete window.marked")
        ctx.set_offline(True)
        REQUESTS.clear()
        offline = page.evaluate("""async () => {
          try { await window.resourceLoader.tryLoadByType('marked'); return 'loaded'; }
          catch (e) { return String(e); }
        }""")
        ctx.set_offline(False)
        offline_urls = [url for url, _ in REQUESTS]
        check('离线只尝试本地且不访问公网', '离线' in offline
              and offline_urls in ([], [BASE + '/static/marked/marked.min.js']),
              f'{offline} | {offline_urls}')

        page.screenshot(path=os.path.join(SHOT, 'cdn_fallback.png'))
        check('回退过程无 CSP 违规', not CSP_ERRORS, '; '.join(CSP_ERRORS[:2]))
        browser.close()
except Exception as exc:
    FAILED.append('浏览器运行异常')
    print('浏览器运行异常：', str(exc)[:800])
finally:
    cleanup()
    server.close()

print(f'—— 结果: {"全部通过" if not FAILED else "失败 " + ", ".join(FAILED)} ——')
print(f'通过 {len(CHECKED) - len(FAILED)}/{len(CHECKED)}')
sys.exit(0 if not FAILED else 1)
