# -*- coding: utf-8 -*-
"""GeoGebra 真实浏览器 E2E：直接 .ggb 与上传目录包装（2026-11-17）。

隔离库 itstudy_e2e + Edge：验证本地引擎的模型 API、目录桥接、课堂切换、
返回目录、消息来源/资源边界/隐藏文件，以及测验消息转发。
--real-courseware 使用已下载到 data/e2e_artifacts 的实际电磁波课件；
未指定时使用可提交的 sample.ggb 和同结构的目录夹具，不访问线上站点。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_geogebra_browser.py --real-courseware
"""
import argparse
import base64
import io
import json
import os
import shutil
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_geogebra')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-geogebra'
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'tools'))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AttendanceRecord, Class, ClassroomSession,  # noqa: E402
                        Resource, Student, SystemConfig, Teacher, TeachingSession, teacher_class)
from e2e_common import reset_shared_state  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from waitress import create_server  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--real-courseware', action='store_true')
parser.add_argument('--real-spa', action='store_true', help='验证知了 SPA 与历史地图原始诊断副本')
parser.add_argument('--lan-http', action='store_true',
                    help='模拟非安全上下文（移除 crypto.randomUUID）')
ARGS = parser.parse_args()
SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__ggb_e2e_cls_{SFX}'
TEACHER_NAME = f'__ggb_e2e_t_{SFX}'
STUDENT_NUMBER = f'__ggb_e2e_s_{SFX}'
PASSWORD = 'GgbE2EPass1'
DIR = f'__ggb_e2e_{SFX}'
DIR_PATH = Path('static') / 'uploads' / DIR
FIXTURE = Path('tests') / 'fixtures' / 'sample.ggb'
PACKAGE = 'AI物理课件-ggbzls'
TITLE = '电磁波（光波）传播示意图'
PORT = 5021
BASE = f'http://127.0.0.1:{PORT}'
ROOT_URL = f'/static/uploads/{DIR}/'
CATALOG_URL = ROOT_URL + PACKAGE + '/index.html'
app = create_app()
reset_shared_state(app)
FAILED = []
IDS = {}
SHOT = Path('data') / 'e2e_geogebra'
CSP_VIOLATIONS = []
EXTERNAL_REQUESTS = []
DEPLOY_URLS = []
FORWARDED = []
CHECKED = []
FILE_RESPONSES = []
CONSOLE_ERRORS = []
MIRROR_RESPONSES = []
WORKER_RESPONSES = []
RAW_UPLOADS = []
PORTAL_REL = '3D可视化/index.html'
SPA_REL = '3D可视化/学科资源/平台资源/知了实验室SPA/index-offline.html'
HISTORY_REL = '3D可视化/学科资源/历史/3D中国地图·史料时间轴(Three.js).html'


def check(name, ok, detail=''):
    CHECKED.append(name)
    print(('✓ ' if ok else '✗ ') + name + (f' | {detail}' if detail else ''))
    if not ok:
        FAILED.append(name)


def wait_for(fn, timeout, label):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.2)
    raise AssertionError(f'等待超时: {label}')


def cleanup():
    with app.app_context():
        if IDS.get('res'):
            TeachingSession.query.filter_by(resource_id=IDS['res']).delete(
                synchronize_session=False)
            Resource.query.filter_by(id=IDS['res']).delete(synchronize_session=False)
        if IDS.get('stu'):
            AttendanceRecord.query.filter_by(student_id=IDS['stu']).delete(
                synchronize_session=False)
            Student.query.filter_by(id=IDS['stu']).delete(synchronize_session=False)
        if IDS.get('teacher'):
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == IDS['teacher']))
            Teacher.query.filter_by(id=IDS['teacher']).delete(synchronize_session=False)
        if IDS.get('cls'):
            ClassroomSession.query.filter_by(class_id=IDS['cls']).delete(
                synchronize_session=False)
            Class.query.filter_by(id=IDS['cls']).delete(synchronize_session=False)
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
    shutil.rmtree(DIR_PATH, ignore_errors=True)


def courseware_fixture():
    """复制诊断副本到本地隔离夹具，不改原副本或线上资源。"""
    course = DIR_PATH / PACKAGE
    course.mkdir(parents=True)
    if ARGS.real_courseware:
        artifacts = Path('data') / 'e2e_artifacts'
        required = ('remote_physics_index.html', 'remote_physics_viewer.html',
                    'remote_physics_catalog.js', 'remote_em_wave_5306.ggb')
        if not all((artifacts / name).is_file() for name in required):
            raise AssertionError('--real-courseware 缺少实际课件诊断副本')
        catalog = json.loads((artifacts / 'remote_physics_catalog.js').read_text(
            encoding='utf-8').split('=', 1)[1].strip().rstrip(';'))
        selected = [item for item in catalog['items'] if item['title'] == TITLE]
        assert len(selected) == 1, '实际目录必须包含唯一的目标课件'
        item = selected[0]
        item['thumb'] = ''  # 不测试无关缩略图；目录原 HTML 和模型不改。
        catalog['items'] = [item]
        shutil.copy(artifacts / 'remote_physics_index.html', course / 'index.html')
        shutil.copy(artifacts / 'remote_physics_viewer.html', course / 'viewer.html')
        model = artifacts / 'remote_em_wave_5306.ggb'
        print(f'实际课件诊断副本：{model.stat().st_size} 字节')
    else:
        item = {'id': 'em-wave', 'title': TITLE,
                'file': '大学物理/电磁波（光波）传播示意图_5306.ggb'}
        catalog = {'items': [item]}
        (course / 'index.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"><script src="catalog.js"></script></head><body>
<div id="content"></div><div id="overlay" hidden><div id="stage"></div></div>
<script>
const item = window.CATALOG.items[0];
const card = document.createElement('button'); card.dataset.id = item.id;
card.className = 'card'; card.textContent = item.title;
document.getElementById('content').append(card);
card.onclick = () => {
  const frame = document.createElement('iframe');
  frame.src = 'viewer.html?file=' + encodeURIComponent(item.file) +
    '&title=' + encodeURIComponent(item.title);
  document.getElementById('stage').append(frame);
  document.getElementById('overlay').hidden = false;
};
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('overlay').hidden = true;
    document.getElementById('stage').replaceChildren();
  }
});
</script></body></html>''', encoding='utf-8')
        (course / 'viewer.html').write_text('''<!doctype html><html><head>
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
</head><body>旧版包装播放器，不应执行</body></html>''', encoding='utf-8')
        model = FIXTURE
    (course / 'catalog.js').write_text('window.CATALOG = ' + json.dumps(
        catalog, ensure_ascii=False) + ';', encoding='utf-8')
    relative = PACKAGE + '/' + item['file']
    target = DIR_PATH / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(model, target)
    shutil.copy(FIXTURE, DIR_PATH / 'demo.ggb')
    shutil.copy(FIXTURE, course / 'hidden.ggb')
    # 特殊字符应按文件路径编码，不能变成 URL 片段或破坏脚本文本。
    special = PACKAGE + "/含 空格#引号'.ggb"
    shutil.copy(FIXTURE, DIR_PATH / special)
    (course / 'plain.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body><p id="plainMarker">普通 HTML 课件</p>
<button id="submitQuiz" onclick="parent.postMessage({type:'ITSTUDY_QUIZ_RESULT',
resource_id:999999,score:5,total:10},'*')">提交测验</button></body></html>''', encoding='utf-8')
    # 直接内联 GeoGebra 的课件：官方引导脚本被适配为本地副本，桥接把
    # 默认 codebase 固定到随包引擎，opaque 沙箱另有内存存储兜底。
    shutil.copy(FIXTURE, course / 'inline-demo.ggb')
    (course / 'ggb-inline.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8">
<script src="https://www.geogebra.org/apps/deployggb.js"></script>
</head><body>
<div id="ggb" style="width:640px;height:420px"></div>
<p id="ggbMarker">ggb</p>
<script>
try {
  localStorage.setItem('probe', 'ok');
  var storage = localStorage.getItem('probe');
} catch (e) { var storage = 'ERR:' + e.name; }
document.getElementById('ggbMarker').textContent = 'STORAGE-' + storage;
var params = {
  appName: 'classic', width: 640, height: 420,
  filename: 'inline-demo.ggb', showMenuBar: false, showToolBar: false,
  showAlgebraInput: false, enableRightClick: false,
  appletOnLoad: function () {
    window.__ggbReady = true;
    document.getElementById('ggbMarker').textContent = 'GGB-OK:' + storage;
  }
};
var applet = new GGBApplet(params, true);
applet.inject('ggb');
</script></body></html>''', encoding='utf-8')
    # 现场复现路径：主页卡片 → 镜像子页面 → 内联 GeoGebra。
    (course / 'ggb-cards.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body>
<button id="ggbCard" onclick="location.href='ggb-inline.html'">GeoGebra 实验</button>
</body></html>''', encoding='utf-8')
    # 三维课件把 three.js 内联为 data: 模块（importmap + 动态 import）。
    module = base64.b64encode(
        b"export const value = 'OK';").decode('ascii')
    (course / 'data-module.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8">
<script type="importmap">{"imports":{"helper":"data:text/javascript;base64,%s"}}</script>
</head><body><p id="dataMarker">data</p>
<script type="module">
import { value } from 'helper';
document.getElementById('dataMarker').textContent = 'DATA-' + value;
</script></body></html>''' % module, encoding='utf-8')
    # opaque 沙箱内纹理图片必须走 CORS 才能 canvas.getImageData。
    (course / 'cors.png').write_bytes(base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ'
        'AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))
    (course / 'cors-image.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body>
<p id="corsMarker">cors</p>
<script>
var img = new Image();
img.onload = function () {
  try {
    var c = document.createElement('canvas'); c.width = c.height = 8;
    var ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0, 8, 8);
    ctx.getImageData(0, 0, 1, 1);
    document.getElementById('corsMarker').textContent = 'CORS-OK';
  } catch (e) {
    document.getElementById('corsMarker').textContent = 'CORS-FAIL:' + e.name;
  }
};
img.onerror = function () {
  document.getElementById('corsMarker').textContent = 'CORS-LOAD-FAIL';
};
img.src = 'cors.png';
</script></body></html>''', encoding='utf-8')
    # 真实目录层级是 location 相对解析的基址，不能使用 about:srcdoc。
    (course / 'phys.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body>
<p id="physMarker">物理之美</p>
<script>
try {
  const resolved = new URL('lab-data/em.ggb', location.href);
  document.getElementById('physMarker').textContent =
    'PHYS-OK:' + (location.protocol === 'http:'
                  && resolved.pathname.endsWith('/lab-data/em.ggb'));
} catch (e) {
  document.getElementById('physMarker').textContent = 'PHYS-FAIL:' + e.message;
}
</script></body></html>''', encoding='utf-8')
    # 子页面、脚本和样式必须继续使用同一镜像目录。
    (course / 'lab.css').write_text('#labMarker{color:rgb(1,2,3)}', encoding='utf-8')
    (course / 'lab.js').write_text(
        "document.getElementById('labMarker').textContent='LAB-JS-OK';",
        encoding='utf-8')
    (course / 'sub.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body><p id="subMarker">sub</p>
<script>document.getElementById('subMarker').textContent='SUB-OK';</script>
</body></html>''', encoding='utf-8')
    (course / 'lab.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"><link rel="stylesheet" href="lab.css"></head><body>
<p id="labMarker">lab</p><iframe id="labSub" src="sub.html"></iframe>
<script src="lab.js"></script></body></html>''', encoding='utf-8')
    # three.js 依赖课件：CDN 引用被桥接改写为本地模块，页面内
    # location 基准构造的 URL 落回镜像路由（保留目录结构）。
    (course / 'three-lab.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body><p id="threeMarker">three</p>
<script type="module">
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/controls/OrbitControls.js';
document.getElementById('threeMarker').textContent =
  'THREE-OK:' + THREE.REVISION + ':' + typeof OrbitControls;
</script></body></html>''', encoding='utf-8')
    if ARGS.real_spa:
        artifacts = Path('data/e2e_artifacts')
        required = [artifacts / 'zhiliao_spa' / 'index-offline.html',
                    artifacts / 'history_original.html', artifacts / '3d_index.html',
                    artifacts / 'history_engine' / 'three.min.js',
                    artifacts / 'history_engine' / 'OrbitControls.js',
                    artifacts / 'history_engine' / 'katex.min.css',
                    artifacts / 'history_engine' / 'katex.min.js',
                    artifacts / 'history_engine' / 'auto-render.min.js']
        if not all(path.is_file() for path in required):
            raise AssertionError('--real-spa 缺少原始课件诊断副本')
        shutil.copytree(artifacts / 'zhiliao_spa', (DIR_PATH / SPA_REL).parent)
        (DIR_PATH / HISTORY_REL).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(artifacts / 'history_original.html', DIR_PATH / HISTORY_REL)
        shutil.copy(artifacts / '3d_index.html', DIR_PATH / PORTAL_REL)
        for name in ('three.min.js', 'OrbitControls.js'):
            target = DIR_PATH / '3D可视化' / '_cdn' / 'three' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(artifacts / 'history_engine' / name, target)
        for name in ('katex.min.css', 'katex.min.js', 'auto-render.min.js'):
            target = DIR_PATH / '3D可视化' / '_cdn' / 'katex' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(artifacts / 'history_engine' / name, target)
        border_dir = (DIR_PATH / HISTORY_REL).parent / '3D中国地图-边界数据'
        border_dir.mkdir()
        geometry = {'type': 'FeatureCollection', 'features': [{
            'type': 'Feature', 'properties': {'name': '隔离测试区域', 'adcode': 0},
            'geometry': {'type': 'Polygon', 'coordinates': [
                [[100, 20], [130, 20], [130, 50], [100, 50], [100, 20]]]},
        }]}
        (border_dir / '100000_full.json').write_text(json.dumps(geometry), encoding='utf-8')
    with zipfile.ZipFile(model) as archive:
        xml = ElementTree.fromstring(archive.read('geogebra.xml'))
        names = {el.get('label') for el in xml.findall('./construction/element')}
    return item['id'], relative, special, names


def new_page(browser):
    ctx = browser.new_context(base_url=BASE, viewport={'width': 1500, 'height': 920})
    ctx.add_init_script("""window.__ggbOpenEvents = []; window.__coursewareDraws = 0;
      for (const ctor of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
        if (!ctor) continue;
        for (const name of ['drawArrays', 'drawElements']) {
          const original = ctor.prototype[name];
          ctor.prototype[name] = function (...args) {
            window.__coursewareDraws++; return original.apply(this, args);
          };
        }
      }
      window.addEventListener('message', e => {
        if (e.data && e.data.type === 'ITSTUDY_GGB_OPEN') window.__ggbOpenEvents.push(e.data);
      });""")
    if ARGS.lan_http:
        ctx.add_init_script("""
          try { delete window.Crypto.prototype.randomUUID; } catch (e) {}
          try { delete window.crypto.randomUUID; } catch (e) {}
        """)
    page = ctx.new_page()
    page.on('pageerror', lambda e: FAILED.append('pageerror:' + str(e)))
    page.on('console', lambda m: CSP_VIOLATIONS.append(m.text)
            if m.type == 'error' and ('Content Security Policy' in m.text or 'Refused to' in m.text)
            else None)
    page.on('console', lambda m: CONSOLE_ERRORS.append((m.type, m.text))
            if m.type == 'error' else None)
    page.on('response', lambda r: MIRROR_RESPONSES.append((r.url, r.status))
            if '/study/courseware-view/' in r.url else None)
    page.on('response', lambda r: WORKER_RESPONSES.append((
        r.url, r.status, r.headers.get('access-control-allow-origin'),
        r.headers.get('content-type'),
        r.request.all_headers().get('origin')))
        if 'heart-volume.worker' in r.url else None)
    page.on('requestfailed', lambda r: WORKER_RESPONSES.append((
        'FAILED', r.url, str(r.failure), '', ''))
        if 'heart-volume.worker' in r.url else None)
    page.on('request', lambda r: EXTERNAL_REQUESTS.append(r.url)
            if not r.url.startswith((BASE, 'data:', 'blob:')) else None)
    page.on('response', lambda r: DEPLOY_URLS.append(r.url) if 'deployggb.js' in r.url else None)
    page.on('response', lambda r: FILE_RESPONSES.append((
        r.url, r.status, r.request.all_headers().get('origin'),
        bool(r.request.all_headers().get('cookie'))))
        if '100000_full.json' in r.url else None)

    def capture_quiz(route):
        FORWARDED.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"success":true}')

    ctx.route('**/api/resource_quiz/submit', capture_quiz)
    return ctx, page


def login_teacher(page):
    page.goto('/teacher/login')
    page.fill('input[name="username"]', TEACHER_NAME)
    mode = page.locator('#readonlyMode')
    if mode.count() and mode.is_enabled() and mode.is_checked():
        mode.uncheck()
    page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(has=page.locator('input[name="username"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/teacher/*', timeout=20000)


def login_student(page):
    page.goto('/')
    page.fill('input[name="student_number"]', STUDENT_NUMBER)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(has=page.locator('input[name="student_number"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/student/home', timeout=20000)


def model_state(frame):
    return frame.locator('body').evaluate("""() => {
      const api = window.ggbApplet;
      return {
        ready: !!window.__ggbReady && !!api && typeof api.getObjectNumber === 'function',
        count: api && typeof api.getObjectNumber === 'function' ? api.getObjectNumber() : 0,
        names: api && typeof api.getAllObjectNames === 'function' ? api.getAllObjectNames() : []
      };
    }""")


def wait_model(frame, label, names=None):
    wait_for(lambda: model_state(frame)['ready'] and model_state(frame)['count'] > 0,
             40, label + ' API/模型就绪')
    state = model_state(frame)
    check(label + '：实际模型已加载', state['count'] > 0 and (
        not names or len(set(state['names']) & names) >= min(10, len(names))),
        f'{state["count"]} 个对象')
    check(label + '：画布已渲染', frame.locator('canvas').count() > 0)
    return state


def open_from_lesson(page, label):
    page.goto(f'/study/lesson/{IDS["res"]}?mode=classroom')
    page.locator('.ch-item[data-id="demo"]').click()
    frame = page.frame_locator('#linkFrame')
    frame.locator('#ggbContainer').wait_for(state='visible', timeout=20000)
    wait_model(frame, label + '直接 .ggb')
    return frame


def directory_preview(page, frame_id, item_id, names, label):
    directory = page.frame_locator('#' + frame_id)
    # 探测是异步的：先等镜像路由导航完成，再检查帧地址与注入。
    wait_for(lambda: '/study/courseware-view/' in (
        page.locator('#' + frame_id).get_attribute('src') or ''), 10,
        label + '：镜像路由导航')
    frame_src = page.locator('#' + frame_id).get_attribute('src') or ''
    check(label + '：课件经镜像路由加载',
          '/study/courseware-view/' in frame_src, frame_src.rsplit('/', 1)[-1])
    check(label + '：课件不再使用 srcdoc',
          page.locator('#' + frame_id).get_attribute('srcdoc') is None)
    check(label + '：GGB 接管脚本已注入',
          directory.locator('script[data-host-origin]').count() == 1)
    check(label + '：记录原始来源用于测验转发',
          page.locator('#' + frame_id).get_attribute('data-source-url') == CATALOG_URL)
    directory.locator(f'.card[data-id="{item_id}"]').wait_for(state='visible', timeout=20000)
    for attempt in range(2):
        started = time.monotonic()
        directory.locator(f'.card[data-id="{item_id}"]').click()
        overlay = page.locator('.ggb-course-overlay')
        overlay.wait_for(state='visible', timeout=10000)
        src = overlay.locator('iframe').get_attribute('src')
        check(label + f'第 {attempt + 1} 次：播放器绑定当前资源',
              src.startswith(f'/study/geogebra/{IDS["res"]}?') and 'embed=1' in src, src)
        engine = page.frame_locator('.ggb-course-overlay iframe')
        engine.locator('#ggbContainer').wait_for(state='visible', timeout=20000)
        wait_model(engine, label + f'第 {attempt + 1} 次', names)
        elapsed = (time.monotonic() - started) * 1000
        print(f'{label}第 {attempt + 1} 次加载：{elapsed:.0f} ms')
        page.screenshot(path=str(SHOT / f'{label}_{attempt + 1}.png'))
        overlay.locator('button').click()
        wait_for(lambda: directory.locator('#overlay').is_hidden(), 5, '返回原目录')
        check(label + f'第 {attempt + 1} 次：关闭释放播放器并返回目录',
              overlay.is_hidden() and overlay.locator('iframe').get_attribute('src') == 'about:blank'
              and directory.locator('#stage iframe').count() == 0)
    return directory


def post_from_directory(directory, data):
    directory.locator('body').evaluate('(el, data) => parent.postMessage(data, "*")', data)


def bridge_boundaries(page, directory, frame_id):
    previous = page.evaluate('() => window.__ggbOpenEvents.at(-1)')
    assert previous and previous.get('token'), '预览必须携带本次导航令牌'
    overlay = page.locator('.ggb-course-overlay')
    for origin, wrong_source in (('https://example.com', False), (BASE, True)):
        page.evaluate("""({msg,origin,wrongSource,frameId}) => {
          window.dispatchEvent(new MessageEvent('message', {data:msg,origin,
            source:wrongSource ? window : document.getElementById(frameId).contentWindow}));
        }""", {'msg': previous, 'origin': origin, 'wrongSource': wrong_source, 'frameId': frame_id})
        check('桥接拒绝伪造来源：' + (origin if not wrong_source else '错误窗口'), overlay.is_hidden())
    bad_paths = [
        BASE + ROOT_URL + '../other/model.ggb',
        BASE + ROOT_URL + 'dir/%2e%2e%2fmodel.ggb',
        BASE + ROOT_URL + 'dir%5cmodel.ggb',
        BASE + ROOT_URL + 'dir./model.ggb',
        BASE + ROOT_URL + 'MODEL~1.GGB',
        BASE + ROOT_URL + 'model.txt',
        BASE + ROOT_URL + 'model%00.ggb',
        'https://example.com/model.ggb',
        BASE + ROOT_URL.rstrip('/') + '-other/model.ggb',
    ]
    for url in bad_paths:
        post_from_directory(directory, dict(previous, url=url))
        page.wait_for_timeout(40)
        check('桥接拒绝跨资源/异常路径：' + url.split(ROOT_URL)[-1], overlay.is_hidden())
    # 帧自报 resourceId 不参与受信 URL 的构建。
    post_from_directory(directory, dict(previous, resourceId=999999))
    overlay.wait_for(state='visible', timeout=5000)
    check('桥接不采信帧自报资源 ID', overlay.locator('iframe').get_attribute('src').startswith(
        f'/study/geogebra/{IDS["res"]}?'))
    overlay.locator('button').click()
    return previous


def open_portal_experiment(frame, key):
    frame.locator('header.hero h1').wait_for(state='visible', timeout=15000)
    link = frame.locator(f'a[href*="{key}"]').first
    link.wait_for(state='attached', timeout=15000)
    if not link.is_visible():
        frame.locator(f'details:has(a[href*="{key}"]) > summary').first.click()
    link.click()


def verify_real_spa(frame, label, expected):
    try:
        frame.locator('canvas').first.wait_for(state='visible', timeout=40000)
    except Exception:
        frame.locator('body').screenshot(path=str(SHOT / (label + '_failure.png')))
        print(label + ' 页面内容：', frame.locator('body').inner_text()[:500])
        print(label + ' worker-shim:', frame.locator('html').get_attribute(
            'data-itstudy-worker-shim'))
        print(label + ' boot:', frame.locator('html').evaluate(
            '() => ({loaded: window.__ITSTUDY_BOOTSTRAP_LOADED__, '
            'origin: location.origin, windowOrigin: window.origin, '
            'parent: window.parent !== window, worker: typeof Worker, '
            'relay: !!window.__ITSTUDY_WORKER_RELAY__})'))
        print(label + ' CSP:', CSP_VIOLATIONS[-5:])
        print(label + ' 控制台错误：', CONSOLE_ERRORS[-10:])
        raise
    try:
        wait_for(lambda: frame.locator('body').evaluate('() => window.__coursewareDraws') > 0,
                 45, label + '实际 WebGL 绘制')
    except AssertionError:
        print(label + ' WebGL 诊断：', frame.locator('body').evaluate(
            '() => ({url:location.href, draws:window.__coursewareDraws, '
            'text:document.body.innerText.slice(0,400)})'))
        print(label + ' CSP/页面错误：', CSP_VIOLATIONS[-3:], FAILED[-3:])
        print(label + ' Worker 响应：', WORKER_RESPONSES[-4:])
        frame.locator('body').screenshot(path=str(SHOT / (label + '_draw_failure.png')))
        raise
    wait_for(lambda: frame.locator('body').evaluate('() => window.__coursewareDraws') > 10,
             20, label + '实际 WebGL 绘制')
    state = frame.locator('body').evaluate('() => ({url:location.href,draws:window.__coursewareDraws})')
    check(label + '：真实实验已绘制', state['draws'] > 0)
    check(label + '：实验内容匹配', expected in frame.locator('body').inner_text())
    check(label + '：逻辑路由仍在授权目录内', '/study/courseware-view/' in state['url']
          and '#/experiment/' in state['url'])
    check(label + '：动态模块样式已应用', frame.locator('body').evaluate(
        '() => Array.from(document.styleSheets).some(s => s.href && s.href.includes("lab-workspace"))'))


def verify_history(frame, label):
    frame.locator('#app canvas').wait_for(state='visible', timeout=30000)
    wait_for(lambda: frame.locator('#status').is_hidden(), 20, label + '边界数据已加载')
    check(label + '：原始地图引擎完成绘制', frame.locator('body').evaluate(
        '() => window.__coursewareDraws > 10'))
    frame.locator('#yslider').press('End')
    check(label + '：时间轴仍可交互', '解放战争时期' in frame.locator('#phase').inner_text())


def nginx_upload_html(environ, start_response):
    from werkzeug.wrappers import Request
    path = Request(environ).path
    if path.startswith(ROOT_URL) and path.lower().endswith(('.html', '.htm')):
        target = (DIR_PATH / path[len(ROOT_URL):]).resolve()
        if target.is_relative_to(DIR_PATH.resolve()) and target.is_file():
            data = target.read_bytes()
            RAW_UPLOADS.append(path)
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'),
                                     ('Content-Length', str(len(data))), ('Cache-Control', 'no-cache')])
            return [data]
    return app(environ, start_response)


server = None
try:
    item_id, model_relative, special_relative, expected_names = courseware_fixture()
    with app.app_context():
        cls = Class(name=CLASS_NAME)
        teacher = Teacher(username=TEACHER_NAME, display_name='GGB E2E教师')
        teacher.set_password(PASSWORD)
        teacher.classes.append(cls)
        stu = Student(name='GGB E2E学生', student_number=STUDENT_NUMBER,
                      student_class=CLASS_NAME, has_changed_password=True)
        stu.set_password(PASSWORD)
        db.session.add_all([cls, teacher, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        res = Resource(title=f'GGB资源_{SFX}', url=CATALOG_URL,
                       show_in_student=True, show_in_classroom=True,
                       creator_type='teacher', creator_teacher_id=teacher.id,
                       creator_name='GGB E2E教师', quiz_mode='none',
                       file_permissions=json.dumps({PACKAGE + '/hidden.ggb': {'show': False}}),
                       lesson_tree=json.dumps([{'id': 'section', 'title': 'GGB课堂', 'items': [
                           {'id': 'demo', 'title': 'demo', 'kind': 'geogebra', 'src': 'demo.ggb'},
                           {'id': 'catalog', 'title': '物理课件目录', 'kind': 'link', 'src': PACKAGE + '/index.html'},
                           {'id': 'plain', 'title': '普通 HTML 课件', 'kind': 'link', 'src': PACKAGE + '/plain.html'},
                           {'id': 'phys', 'title': '物理之美', 'kind': 'link', 'src': PACKAGE + '/phys.html'},
                           {'id': 'lab', 'title': '知了实验室', 'kind': 'link', 'src': PACKAGE + '/lab.html'},
                           {'id': 'three-lab', 'title': '3D 实验室(three)', 'kind': 'link', 'src': PACKAGE + '/three-lab.html'},
                           {'id': 'ggb-inline', 'title': 'GeoGebra 数学课件', 'kind': 'link', 'src': PACKAGE + '/ggb-cards.html'},
                           {'id': 'data-module', 'title': 'data 模块课件', 'kind': 'link', 'src': PACKAGE + '/data-module.html'},
                           {'id': 'cors-image', 'title': '纹理画布课件', 'kind': 'link', 'src': PACKAGE + '/cors-image.html'},
                       ]}], ensure_ascii=False))
        if ARGS.real_spa:
            tree = json.loads(res.lesson_tree)
            tree[0]['items'].extend([
                {'id': 'portal', 'title': '真实3D资源目录', 'kind': 'link', 'src': PORTAL_REL},
                {'id': 'history-map', 'title': '历史地图', 'kind': 'link', 'src': HISTORY_REL},
            ])
            res.lesson_tree = json.dumps(tree, ensure_ascii=False)
        db.session.add(res)
        db.session.flush()
        db.session.add(TeachingSession(resource_id=res.id, teacher_id=teacher.id,
                                       teacher_name=teacher.display_name, class_id=cls.id, status='active'))
        db.session.commit()
        SystemConfig.set('courseware_public_enabled', 'false')
        db.session.commit()
        IDS.update(cls=cls.id, teacher=teacher.id, stu=stu.id, res=res.id)
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
    server = create_server(nginx_upload_html, host='127.0.0.1', port=PORT, threads=8)
    threading.Thread(target=server.run, daemon=True).start()
    SHOT.mkdir(parents=True, exist_ok=True)
    from urllib.request import urlopen
    with urlopen(BASE + quote(CATALOG_URL), timeout=15) as response:
        check('Nginx 直服原始 HTML 的拓扑已复现',
              response.status == 200 and b'data-content-root' not in response.read())
    raw_before = len(RAW_UPLOADS)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        cctx, cp = new_page(browser)
        login_teacher(cp)
        cp.goto('/study/link?' + urlencode({'url': CATALOG_URL, 'resource_id': IDS['res'], 'title': TITLE}))
        directory_preview(cp, 'mainFrame', item_id, expected_names, '引擎冷启动目录')
        cctx.close()
        tctx, tp = new_page(browser)
        login_teacher(tp)
        check('教师登录', '/teacher/' in tp.url and '/teacher/login' not in tp.url)
        open_from_lesson(tp, '教师')
        tp.screenshot(path=str(SHOT / 'teacher_geogebra.png'))
        tp.locator('.ch-item[data-id="catalog"]').click()
        tdirectory = directory_preview(tp, 'linkFrame', item_id, expected_names, '教师课堂目录')
        old_message = bridge_boundaries(tp, tdirectory, 'linkFrame')

        tp.locator('.ch-item[data-id="plain"]').click()
        plain = tp.frame_locator('#linkFrame')
        plain.locator('#plainMarker').wait_for(state='visible', timeout=15000)
        check('课堂上传 HTML 为 opaque sandbox',
              'allow-same-origin' not in tp.locator('#linkFrame').get_attribute('sandbox'))
        check('课堂上传 HTML 无法读取主页面 Cookie', plain.locator('body').evaluate("""() => {
          try { void parent.document.cookie; return false; }
          catch (e) { return e.name === 'SecurityError'; }
        }"""))
        post_from_directory(plain, old_message)
        tp.wait_for_timeout(100)
        check('课堂切换拒绝旧目录迟到消息', tp.locator('.ggb-course-overlay').is_hidden())
        count = len(FORWARDED)
        plain.locator('#submitQuiz').click()
        wait_for(lambda: (tp.wait_for_timeout(40) or len(FORWARDED) > count), 5, '课堂测验转发')
        check('课堂课件测验按当前资源转发', FORWARDED[-1]['resource_id'] == IDS['res'])

        # 把目录页的桥接导航暂存，切到普通课件后再尝试交付，验证迟到的
        # 旧响应不覆盖新课件（导航由浏览器取消，不依赖客户端 fetch 中止）。
        held = {}
        seen_courseware = []

        def hold_catalog_route(route):
            seen_courseware.append(route.request.url)
            if 'index.html' in route.request.url and not held:
                held['route'] = route
                held['response'] = route.fetch()
            else:
                route.continue_()

        tctx.route('**/study/courseware**', hold_catalog_route)
        tp.locator('.ch-item[data-id="catalog"]').click()
        try:
            wait_for(lambda: (tp.wait_for_timeout(40) or bool(held)), 5, '目录导航已挂起')
        except AssertionError:
            print('[HOLD-DEBUG] 拦截到的请求:', seen_courseware)
            print('[HOLD-DEBUG] 当前帧地址:', tp.locator('#linkFrame').get_attribute('src'))
            print('[HOLD-DEBUG] 帧内内容:', tp.frame_locator('#linkFrame').locator('body').inner_text()[:80])
            raise
        tp.locator('.ch-item[data-id="plain"]').click()
        try:
            held['route'].fulfill(response=held['response'])
        except Exception:
            pass  # 导航已被新课件替换，迟到的旧响应不再生效。
        tctx.unroute('**/study/courseware**', hold_catalog_route)
        plain.locator('#plainMarker').wait_for(state='visible', timeout=15000)
        check('取消旧目录导航不覆盖新课件', tp.locator('#linkFrame').get_attribute('data-source-url')
              == ROOT_URL + PACKAGE + '/plain.html')
        open_from_lesson(tp, '目录切换后')
        check('直接播放器导航清除旧桥接状态',
              tp.locator('#linkFrame').get_attribute('srcdoc') is None
              and tp.locator('#linkFrame').get_attribute('data-source-url') is None)

        # 保留目录层级的镜像地址仍可作为 new URL 的解析基址。
        tp.locator('.ch-item[data-id="phys"]').click()
        phys = tp.frame_locator('#linkFrame')
        phys.locator('#physMarker').wait_for(state='visible', timeout=15000)
        check('物理之美式 SPA 课件保留目录结构并正常构造 URL（课堂）',
              phys.locator('#physMarker').inner_text() == 'PHYS-OK:true'
              and '/study/courseware-view/' in tp.locator('#linkFrame').get_attribute('src'),
              phys.locator('#physMarker').inner_text())

        # CSS、JS 与嵌套子页面都应在同一凭证路径下加载。
        tp.locator('.ch-item[data-id="lab"]').click()
        lab = tp.frame_locator('#linkFrame')
        lab.locator('#labMarker').wait_for(state='visible', timeout=15000)
        wait_for(lambda: lab.locator('#labMarker').inner_text() == 'LAB-JS-OK', 8,
                 '知了实验室式相对 JS 加载')
        check('知了实验室式课件保留相对目录',
              '/study/courseware-view/' in tp.locator('#linkFrame').get_attribute('src')
              and tp.locator('#linkFrame').get_attribute('src').endswith(quote(PACKAGE + '/lab.html')),
              '镜像目录内的原始相对路径')
        check('知了实验室式相对 CSS 生效',
              lab.locator('#labMarker').evaluate('el => getComputedStyle(el).color')
              == 'rgb(1, 2, 3)')
        lab_sub = lab.frame_locator('#labSub')
        try:
            lab_sub.locator('#subMarker').wait_for(state='visible', timeout=10000)
        except Exception:
            print('[LAB-DEBUG] linkFrame src:', tp.locator('#linkFrame').get_attribute('src'))
            print('[LAB-DEBUG] sandbox:', tp.locator('#linkFrame').get_attribute('sandbox'))
            print('[LAB-DEBUG] iframe count:', lab.locator('iframe').count())
            if lab.locator('iframe').count():
                print('[LAB-DEBUG] iframe src:',
                      lab.locator('iframe').first.get_attribute('src'))
            print('[LAB-DEBUG] body:', lab.locator('body').inner_text()[:300])
            print('[LAB-DEBUG] mirror:', MIRROR_RESPONSES[-8:])
            print('[LAB-DEBUG] console:', CONSOLE_ERRORS[-8:])
            raise
        wait_for(lambda: lab_sub.locator('#subMarker').inner_text() == 'SUB-OK', 8,
                 '知了实验室式相对子页面')
        check('知了实验室式相对子页面加载',
              lab_sub.locator('#subMarker').inner_text() == 'SUB-OK')

        # 直接内联 GeoGebra 的课件：官方引导脚本经适配为本地副本；
        # opaque 沙箱内 GWT 不能运行，显示时转交宿主受信播放器。
        tp.locator('.ch-item[data-id="ggb-inline"]').click()
        ggb_inline = tp.frame_locator('#linkFrame')
        ggb_inline.locator('#ggbCard').wait_for(state='visible', timeout=15000)
        ggb_inline.locator('#ggbCard').click()
        ggb_inline.locator('#ggbMarker').wait_for(state='visible', timeout=15000)
        try:
            tp.locator('.ggb-course-overlay').wait_for(state='visible', timeout=15000)
        except Exception:
            print('[GGB-INLINE-DEBUG] 标记:', ggb_inline.locator('#ggbMarker').inner_text())
            print('[GGB-INLINE-DEBUG] 控制台:', CONSOLE_ERRORS[-6:])
            print('[GGB-INLINE-DEBUG] deploy:', DEPLOY_URLS[-4:])
            raise
        inline_player = tp.frame_locator('.ggb-course-overlay iframe')
        wait_model(inline_player, '内联 GeoGebra 受信播放器')
        check('上传 HTML 内联 GeoGebra 转交受信播放器',
              '/study/geogebra/' in (
                  tp.locator('.ggb-course-overlay iframe').get_attribute('src') or ''))
        check('opaque 沙箱 localStorage 兜底可用',
              ggb_inline.locator('#ggbMarker').inner_text() == 'STORAGE-ok')
        tp.locator('.ggb-course-overlay button').click()

        # 地理/物理三维课件把 three.js 内联为 data: 模块。
        tp.locator('.ch-item[data-id="data-module"]').click()
        data_frame = tp.frame_locator('#linkFrame')
        data_frame.locator('#dataMarker').wait_for(state='visible', timeout=15000)
        wait_for(lambda: data_frame.locator('#dataMarker').inner_text() == 'DATA-OK',
                 15, 'data: 模块脚本')
        check('课件帧允许 data: 模块脚本',
              data_frame.locator('#dataMarker').inner_text() == 'DATA-OK')

        # opaque 沙箱里纹理图片需走 CORS，否则 canvas.getImageData 污染。
        tp.locator('.ch-item[data-id="cors-image"]').click()
        cors_frame = tp.frame_locator('#linkFrame')
        cors_frame.locator('#corsMarker').wait_for(state='visible', timeout=15000)
        wait_for(lambda: cors_frame.locator('#corsMarker').inner_text() == 'CORS-OK',
                 15, '纹理图片 CORS')
        check('opaque 沙箱纹理画布未被污染',
              cors_frame.locator('#corsMarker').inner_text() == 'CORS-OK')

        if ARGS.real_spa:
            tp.locator('.ch-item[data-id="portal"]').click()
            portal = tp.frame_locator('#linkFrame')
            open_portal_experiment(portal, 'chem-tyndall')
            verify_real_spa(portal, '教师课堂知了 SPA', '丁达尔')
            tp.screenshot(path=str(SHOT / 'real_spa_teacher.png'))
            portal.locator('body').evaluate('() => history.back()')
            open_portal_experiment(portal, 'd52651d590fd')
            verify_real_spa(portal, '教师课堂知了心脏实验', '心脏')
            tp.locator('.ch-item[data-id="history-map"]').click()
            verify_history(tp.frame_locator('#linkFrame'), '教师课堂历史地图')
            tp.screenshot(path=str(SHOT / 'history_teacher.png'))

        # three.js 依赖课件：CDN 引用被改写为本地副本，模块真实可导入，
        # 且帧地址保留镜像目录结构（location 基准构造的相对 URL 落回镜像路由）。
        tp.locator('.ch-item[data-id="three-lab"]').click()
        three_frame = tp.frame_locator('#linkFrame')
        three_frame.locator('#threeMarker').wait_for(state='visible', timeout=30000)
        try:
            wait_for(lambda: 'THREE-OK:186:function' in three_frame.locator(
                '#threeMarker').inner_text(), 25, 'three 本地模块导入')
        except AssertionError:
            print('[THREE-DEBUG] 帧地址:', tp.locator('#linkFrame').get_attribute('src'))
            print('[THREE-DEBUG] 标记:', three_frame.locator('#threeMarker').inner_text())
            print('[THREE-DEBUG] 页面含改写:', '/study/three/' in three_frame.locator('body').evaluate(
                '() => document.documentElement.outerHTML'))
            raise
        check('three 依赖经本地副本加载（课堂）',
              'THREE-OK:186:function' in three_frame.locator('#threeMarker').inner_text(),
              three_frame.locator('#threeMarker').inner_text())
        check('three 课件走镜像路由且保留目录结构',
              '/study/courseware-view/' in (tp.locator('#linkFrame').get_attribute('src') or ''))

        sctx, sp = new_page(browser)
        login_student(sp)
        check('学生登录', '/student/home' in sp.url)
        open_from_lesson(sp, '学生')
        sp.goto('/study/link?' + urlencode({'url': CATALOG_URL, 'resource_id': IDS['res'], 'title': TITLE}))
        check('上传目录仍为 opaque sandbox', 'allow-same-origin' not in sp.locator('#mainFrame').get_attribute('sandbox'))
        sdirectory = directory_preview(sp, 'mainFrame', item_id, expected_names, '学生学习目录')
        check('上传 HTML 无法读取主页面 Cookie', sdirectory.locator('body').evaluate("""() => {
          try { void parent.document.cookie; return false; }
          catch (e) { return e.name === 'SecurityError'; }
        }"""))
        bridge_boundaries(sp, sdirectory, 'mainFrame')
        message = sp.evaluate('() => window.__ggbOpenEvents.at(-1)')
        post_from_directory(sdirectory, dict(message, url=BASE + ROOT_URL + PACKAGE + '/hidden.ggb'))
        overlay = sp.locator('.ggb-course-overlay')
        overlay.wait_for(state='visible', timeout=5000)
        hidden_frame = sp.frame_locator('.ggb-course-overlay iframe')
        hidden_frame.locator('body').wait_for(state='visible', timeout=10000)
        wait_for(lambda: '404' in hidden_frame.locator('body').inner_text(), 10, '隐藏模型被拒绝')
        check('目录桥接不能绕过隐藏文件权限', hidden_frame.locator('#ggbContainer').count() == 0)
        overlay.locator('button').click()
        count = len(FORWARDED)
        post_from_directory(sdirectory, {'type': 'ITSTUDY_QUIZ_RESULT', 'resource_id': 999999, 'score': 5, 'total': 10})
        wait_for(lambda: (sp.wait_for_timeout(40) or len(FORWARDED) > count), 5, 'opaque 课件测验转发')
        check('opaque 课件测验按原始来源和当前资源转发', FORWARDED[-1]['resource_id'] == IDS['res'])

        # 学习页 opaque 沙箱下「物理之美」式 SPA 同样保持原静态地址打开。
        sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PACKAGE + '/phys.html',
                                            'resource_id': IDS['res'], 'title': TITLE}))
        phys_link = sp.frame_locator('#mainFrame')
        phys_link.locator('#physMarker').wait_for(state='visible', timeout=15000)
        check('物理之美式 SPA 课件正常构造 URL（学习页）',
              phys_link.locator('#physMarker').inner_text() == 'PHYS-OK:true',
              phys_link.locator('#physMarker').inner_text())
        check('学习页普通课件经受授权的镜像路由',
              '/study/courseware-view/' in (
                  sp.locator('#mainFrame').get_attribute('src') or ''))

        # opaque 沙箱下 three 本地模块导入（模块加载需 CORS，验证镜像/本地路由头）
        sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PACKAGE + '/three-lab.html',
                                            'resource_id': IDS['res'], 'title': TITLE}))
        three_link = sp.frame_locator('#mainFrame')
        three_link.locator('#threeMarker').wait_for(state='visible', timeout=30000)
        wait_for(lambda: 'THREE-OK:186:function' in three_link.locator(
            '#threeMarker').inner_text(), 25, 'opaque 沙箱 three 模块导入')
        check('学习页 opaque 沙箱下 three 本地模块导入',
              'THREE-OK:186:function' in three_link.locator('#threeMarker').inner_text())

        # 学生独立学习页：主页卡片 → 子页面内联 GeoGebra 同样转交受信播放器。
        sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PACKAGE + '/ggb-cards.html',
                                            'resource_id': IDS['res'], 'title': TITLE}))
        inline_link = sp.frame_locator('#mainFrame')
        inline_link.locator('#ggbCard').wait_for(state='visible', timeout=15000)
        inline_link.locator('#ggbCard').click()
        sp.locator('.ggb-course-overlay').wait_for(state='visible', timeout=15000)
        wait_model(sp.frame_locator('.ggb-course-overlay iframe'),
                   '学生学习页内联 GeoGebra 受信播放器')
        check('学生 opaque 学习页内联 GeoGebra 可打开',
              '/study/geogebra/' in (
                  sp.locator('.ggb-course-overlay iframe').get_attribute('src') or ''))
        sp.locator('.ggb-course-overlay button').click()

        sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PACKAGE + '/data-module.html',
                                            'resource_id': IDS['res'], 'title': TITLE}))
        student_data = sp.frame_locator('#mainFrame')
        student_data.locator('#dataMarker').wait_for(state='visible', timeout=15000)
        wait_for(lambda: student_data.locator('#dataMarker').inner_text() == 'DATA-OK',
                 15, '学生 data: 模块脚本')
        check('学生学习页允许 data: 模块脚本',
              student_data.locator('#dataMarker').inner_text() == 'DATA-OK')

        sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PACKAGE + '/cors-image.html',
                                            'resource_id': IDS['res'], 'title': TITLE}),
                referer=BASE + '/study')
        student_cors = sp.frame_locator('#mainFrame')
        student_cors.locator('#corsMarker').wait_for(state='visible', timeout=15000)
        wait_for(lambda: student_cors.locator('#corsMarker').inner_text() == 'CORS-OK',
                 15, '学生纹理图片 CORS')
        check('学生学习页纹理画布未被污染',
              student_cors.locator('#corsMarker').inner_text() == 'CORS-OK')

        # iframe 导航会污染联合会话历史；“返回”必须离开封装页而不是
        # history.back() 回退到课件内部/空白。
        sp.locator('.toolbar .btn-back').click()
        sp.wait_for_url('**/study', timeout=15000)
        check('学习页返回离开封装页',
              sp.url.rstrip('/').endswith('/study')
              and sp.locator('.resource-card').count() > 0)

        if ARGS.real_spa:
            sp.goto('/study/link?' + urlencode({'url': ROOT_URL + PORTAL_REL,
                                                'resource_id': IDS['res']}))
            portal = sp.frame_locator('#mainFrame')
            open_portal_experiment(portal, 'chem-tyndall')
            verify_real_spa(portal, '学生独立学习知了 SPA', '丁达尔')
            check('知了 SPA 未放开同源沙箱', 'allow-same-origin' not in
                  sp.locator('#mainFrame').get_attribute('sandbox'))
            sp.screenshot(path=str(SHOT / 'real_spa_student.png'))
            portal.locator('body').evaluate('() => history.back()')
            open_portal_experiment(portal, 'chem-extraction')
            verify_real_spa(portal, '学生独立学习知了第二个实验', '萃取')
            sp.goto('/study/link?' + urlencode({'url': ROOT_URL + HISTORY_REL,
                                                'resource_id': IDS['res']}))
            verify_history(sp.frame_locator('#mainFrame'), '学生独立学习历史地图')
            sp.screenshot(path=str(SHOT / 'history_student.png'))
            record = FILE_RESPONSES[-1]
            check('历史数据无 Cookie 请求按只读凭证放行',
                  record[1] == 200 and record[2] == 'null' and not record[3])

        sp.goto('/study/link?' + urlencode({'url': f'/study/geogebra/{IDS["res"]}?file=demo.ggb'}))
        wait_model(sp.frame_locator('#mainFrame'), '受信播放器封装页')
        check('仅平台播放器帧使用 allow-same-origin', 'allow-same-origin' in sp.locator('#mainFrame').get_attribute('sandbox'))
        sp.goto(f'/study/geogebra/{IDS["res"]}?' + urlencode({'file': special_relative}))
        wait_model(sp, '特殊字符文件名')
        check('独立播放器高度扣除工具栏', sp.locator('#ggbWrap').evaluate(
            'el => el.getBoundingClientRect().bottom <= innerHeight + 1'))
        sp.screenshot(path=str(SHOT / 'player_standalone.png'))

        sp.goto('/study')
        sp.evaluate("""title => {
          document.querySelectorAll('.resource-card').forEach(c => {
            if (!c.textContent.includes(title)) return;
            const hdr = c.querySelector('.res-header');
            const body = hdr && document.getElementById(hdr.dataset.target);
            if (body && getComputedStyle(body).display === 'none') hdr.click();
          });
        }""", f'GGB资源_{SFX}')
        with sp.expect_popup() as pop:
            sp.locator('a:has-text("打开（GeoGebra）")').first.click()
        player = pop.value
        player.wait_for_load_state('domcontentloaded', timeout=20000)
        wait_model(player, '学习资源文件卡片')
        player.close()

        check('课件导航不再依赖 Nginx 静态 HTML 适配', len(RAW_UPLOADS) == raw_before)
        check('无 CSP 违规', not CSP_VIOLATIONS, '; '.join(CSP_VIOLATIONS[:2]))
        geo_external = [url for url in EXTERNAL_REQUESTS if 'geogebra.org' in url]
        check('目录旧 viewer 未请求官方 GeoGebra 引擎', not geo_external, '; '.join(geo_external[:2]))
        check('deployggb 使用本地文件', bool(DEPLOY_URLS) and all(
            '/static/geogebra/GeoGebra/deployggb.js' in url for url in DEPLOY_URLS),
            '; '.join(sorted(set(DEPLOY_URLS))))
        browser.close()
except Exception as exc:
    FAILED.append('浏览器运行异常')
    print('浏览器运行异常：', repr(exc)[:2000])
finally:
    cleanup()
    if server:
        server.close()

print(f'—— 结果: {"全部通过" if not FAILED else "失败 " + ", ".join(FAILED)} ——')
print(f'通过 {len(CHECKED) - len(FAILED)}/{len(CHECKED)}')
print('截图目录：', SHOT)
sys.exit(0 if not FAILED else 1)
