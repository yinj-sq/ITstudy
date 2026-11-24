# -*- coding: utf-8 -*-
"""化学仿真真实浏览器 E2E（Playwright + Edge 无头）。

覆盖：学生登录 → /chem-lab 三标签 → 离线 Ketcher 绘制（Ketcher wasm）
→ OpenChemLib 3D 构象 + 3Dmol.js 渲染 → 显示模式/截图/清空
→ 本地分子库（Molstar）→ 可视化化学（Three.js）→ 课堂嵌入
→ 无外网请求、无 CSP/JS 错误。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_chem_lab_browser.py
"""
import base64
import io
import os
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_chem_lab')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-chem-lab'
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'tools'))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AttendanceRecord, Class, ClassroomSession,  # noqa: E402
                        Student, Teacher, teacher_class)
from PIL import Image  # noqa: E402

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__chem_e2e_class_{SFX}'
STUDENT_NUMBER = f'__chem_e2e_{SFX}'
TEACHER_NAME = f'__chem_e2e_teacher_{SFX}'
PASSWORD = 'ChemE2ePass123'
PORT = 5013
BASE = f'http://127.0.0.1:{PORT}'

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)

FAILED = []
CHECKED = []


def show(name, ok, detail=''):
    CHECKED.append(name)
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))


def cleanup():
    with app.app_context():
        for stu in Student.query.filter(
                Student.student_number.like('__chem_e2e_%')).all():
            AttendanceRecord.query.filter_by(student_id=stu.id).delete(
                synchronize_session=False)
            db.session.delete(stu)
        for teacher in Teacher.query.filter(
                Teacher.username.like('__chem_e2e_teacher_%')).all():
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == teacher.id))
        Teacher.query.filter(
            Teacher.username.like('__chem_e2e_teacher_%')).delete(
                synchronize_session=False)
        for cls in Class.query.filter(
                Class.name.like('__chem_e2e_class_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            db.session.delete(cls)
        db.session.commit()


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    stu = Student(name='化学仿真E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    teacher = Teacher(username=TEACHER_NAME, display_name='化学课堂E2E教师')
    teacher.set_password(PASSWORD)
    teacher.classes.append(cls)
    db.session.add_all([cls, stu, teacher])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    db.session.commit()
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

from waitress import serve  # noqa: E402

threading.Thread(target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
                 daemon=True).start()
time.sleep(1.5)

from playwright.sync_api import sync_playwright  # noqa: E402

SHOT = os.path.join('data', 'e2e_chem_lab')
os.makedirs(SHOT, exist_ok=True)
page_errors = []
csp_errors = []
external_requests = []

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                                  base_url=BASE, accept_downloads=True)

        def instrument_viewer(route):
            # 去掉条件请求头：304 空响应会让注入标记缺失，且 Playwright
            # 路由回调抛错会中止请求，页面脚本随之不加载。
            headers = {key: value for key, value in route.request.headers.items()
                       if key.lower() not in ('if-none-match', 'if-modified-since')}
            response = route.fetch(headers=headers)
            source = response.text().replace('\r\n', '\n')
            if '/static/js/chem_lab.js' in route.request.url:
                marker = '    return mol3dViewer;\n  }'
                if marker not in source:
                    print('[INSTRUMENT MISS]', route.request.url, response.status,
                          len(source))
                source = source.replace(marker,
                    '    window.__testSketchViewer = mol3dViewer;\n' + marker)
            else:
                marker = "    setBackground('dark');"
                if marker not in source:
                    print('[INSTRUMENT MISS]', route.request.url, response.status,
                          len(source))
                source = source.replace(marker,
                    '    window.__testLibraryViewer = viewer;\n' + marker)
            headers = dict(response.headers)
            headers.pop('content-encoding', None)
            headers.pop('content-length', None)
            route.fulfill(status=200, headers=headers, body=source)

        ctx.route('**/static/js/chem_lab.js*', instrument_viewer)
        ctx.route('**/static/chem-lab/js/viewer-app.js*', instrument_viewer)
        page = ctx.new_page()
        page.on('pageerror', lambda e: page_errors.append(str(e)))

        def on_console(msg):
            text = msg.text or ''
            if msg.type == 'error':
                print('[CONSOLE ERROR]', text[:300])
            if msg.type == 'error' and ('Content Security Policy' in text or
                                        'Refused to' in text):
                csp_errors.append(text[:300])

        page.on('console', on_console)
        page.on('request', lambda req: external_requests.append(req.url)
                if not req.url.startswith((BASE, 'data:', 'blob:')) else None)
        page.on('response', lambda resp: print(
            '[HTTP]', resp.status, resp.url[:180])
            if resp.status >= 400 else None)
        page.on('requestfailed', lambda req: print(
            '[REQFAIL]', req.url[:160],
            (req.failure or '')[:120] if req.failure else ''))

        page.goto('/')
        page.fill('input[name="student_number"]', STUDENT_NUMBER)
        page.fill('input[name="password"]', PASSWORD)
        page.locator('form').filter(
            has=page.locator('input[name="student_number"]')
        ).locator('button[type="submit"]').click()
        # 不用 networkidle：/study 的 AI 面板存在周期性状态请求，偶发永不空闲。
        page.wait_for_url('**/study*', timeout=20000)
        page.wait_for_function("() => document.readyState === 'complete'",
                               timeout=20000)
        show('学生登录', '学习资源' in page.content())

        page.goto('/chem-lab')
        page.wait_for_selector('#chemLab', state='visible', timeout=20000)
        text = page.content()
        show('工作台加载', '化学仿真' in text and 'Ketcher' in text)
        show('三标签齐全', all(k in text for k in
                            ('绘制 + 3D', '可视化化学', '分子库')))
        show('无 MolDraw 外链', 'moldraw' not in text.lower())
        ketcher_src = page.locator('#chemKetcherFrame').get_attribute('src') or ''
        show('Ketcher 同源帧', ketcher_src.startswith('/chem-lab/sketch'), ketcher_src)

        ketcher = page.frame_locator('#chemKetcherFrame')
        try:
            ketcher.locator('.Ketcher-root').wait_for(state='visible', timeout=60000)
            svg_count = ketcher.locator('.Ketcher-root svg').count()
            show('Ketcher 离线编辑器渲染', svg_count > 0, f'svg={svg_count}')
        except Exception as exc:
            show('Ketcher 离线编辑器渲染', False, str(exc)[:160])
        show('离线引擎就绪',
             '就绪' in page.locator('#chemSketchStatus').inner_text(),
             page.locator('#chemSketchStatus').inner_text())
        bond_title = ketcher.locator(
            '[data-testid="bonds"]:visible').get_attribute('title') or ''
        show('Ketcher 工具栏中文', '单键' in bond_title, bond_title)
        try:
            ketcher.locator('[data-testid="settings-button"]:visible').click()
            page.wait_for_timeout(700)
            settings_text = ketcher.locator('body').inner_text()
            show('Ketcher 设置中文',
                 '常规' in settings_text and '字体' in settings_text)
            page.keyboard.press('Escape')
            page.wait_for_timeout(400)
        except Exception as exc:
            show('Ketcher 设置中文', False, str(exc)[:160])
        page.screenshot(path=f'{SHOT}/01_ketcher.png', full_page=True)

        # 示例：乙醇 → OpenChemLib 3D → 3Dmol
        page.select_option('#chemSketchSample', 'CCO')
        try:
            page.wait_for_function(
                "() => document.getElementById('chem3dStatus').textContent.includes('C2H6O')",
                timeout=45000)
        except Exception as exc:
            print('[3D WAIT]', exc)
        show('乙醇 3D 构象生成',
             'C2H6O' in page.locator('#chem3dStatus').inner_text(),
             page.locator('#chem3dStatus').inner_text())
        show('3Dmol 画布渲染',
             page.locator('#chem3dmol canvas').count() > 0)
        show('结构信息联动',
             page.locator('#chemInfoFormula').inner_text().strip() == 'C2H6O',
             page.locator('#chemInfoFormula').inner_text())
        initial_view = page.evaluate('window.__testSketchViewer.getView()')
        page.click('#chem3dSpin')
        page.wait_for_function(
            'initial => window.__testSketchViewer.getView().some((v, i) => Math.abs(v - initial[i]) > 0.01)',
            arg=initial_view, timeout=5000)
        show('3D 自动旋转实际改变视角',
             'active' in (page.locator('#chem3dSpin').get_attribute('class') or '')
             and '自动旋转' in page.locator('#chem3dStatus').inner_text())
        page.click('#chem3dReset')
        reset_view = page.evaluate('window.__testSketchViewer.getView()')
        show('3D 重置恢复初始视角',
             max(abs(a - b) for a, b in zip(initial_view, reset_view)) < 1e-5
             and page.locator('#chem3dSpin').get_attribute('aria-pressed') == 'false',
             page.locator('#chem3dStatus').inner_text())
        page.screenshot(path=f'{SHOT}/02_ethanol_3d.png', full_page=True)

        # 3D 显示模式
        for style in ('sphere', 'stick', 'line', 'ball-and-stick'):
            page.select_option('#chem3dStyle', style)
            page.wait_for_timeout(700)
            show(f'3D 显示模式 {style}',
                 '3D 不可用' not in page.locator('#chem3dStatus').inner_text())
        page.screenshot(path=f'{SHOT}/03_styles.png', full_page=True)

        # 3D 截图下载
        try:
            with page.expect_download(timeout=8000) as dl:
                page.click('#chem3dShot')
            show('3D 截图下载', dl.value.suggested_filename.endswith('.png'),
                 dl.value.suggested_filename)
        except Exception as exc:
            show('3D 截图下载', False, str(exc)[:160])

        # 清空画布
        page.click('#chemSketchClear')
        page.wait_for_timeout(1500)
        show('清空画布', page.locator('#chem3dEmpty').is_visible() and
             '画布为空' in page.locator('#chem3dStatus').inner_text(),
             page.locator('#chem3dStatus').inner_text())

        # 深链：直接载入 SMILES（苯）
        page.goto('/chem-lab?smiles=c1ccccc1')
        page.wait_for_selector('#chemLab', state='visible', timeout=20000)
        try:
            page.wait_for_function(
                "() => document.getElementById('chem3dStatus').textContent.includes('C6H6')",
                timeout=45000)
        except Exception:
            pass
        show('SMILES 深链生成 3D',
             'C6H6' in page.locator('#chem3dStatus').inner_text(),
             page.locator('#chem3dStatus').inner_text())
        show('SMILES 深链绘制',
             page.locator('#chemInfoFormula').inner_text().strip() == 'C6H6',
             page.locator('#chemInfoFormula').inner_text())

        page.click('.chem-nav-item[data-tab="library"]')
        frame = page.frame_locator('#chemViewer')

        def representation_state():
            return frame.locator('body').evaluate("""() => {
              const plugin = window.__testLibraryViewer.plugin;
              return [...plugin.state.data.cells.values()]
                .filter(c => c.obj && c.obj.data && c.obj.data.repr)
                .map(c => ({
                  type: c.params.values.type.name,
                  hidden: !!c.state.isHidden,
                  visible: c.obj.data.repr.state.visible,
                  objects: c.obj.data.repr.renderObjects.length
                }));
            }""")

        def select_library(card):
            title = card.get_attribute('data-title')
            card.click()
            page.wait_for_function("""title => {
              const el = document.getElementById('chemViewStatus');
              return el.dataset.title === title && el.dataset.state === 'ready';
            }""", arg=title, timeout=30000)

        style_types = {'ball-and-stick': 'ball-and-stick', 'spacefill': 'spacefill',
                       'wireframe': 'line', 'cartoon': 'cartoon'}
        cards = page.locator('.chem-library-card').all()
        for card in cards:
            select_library(card)
            molecule = card.get_attribute('data-id')
            modes = ['ball-and-stick', 'spacefill', 'wireframe']
            cartoon = page.locator('#chemViewStyle option[value="cartoon"]')
            if cartoon.is_enabled():
                modes.append('cartoon')
            for mode in modes:
                page.select_option('#chemViewStyle', mode)
                page.wait_for_function("""style => {
                  const el = document.getElementById('chemViewStatus');
                  return el.dataset.style === style && el.dataset.state === 'ready';
                }""", arg=mode, timeout=20000)
                representations = representation_state()
                active = [r for r in representations if not r['hidden'] and r['visible']]
                png = frame.locator('body').evaluate("""async () => {
                  return await window.__testLibraryViewer.plugin.helpers.viewportScreenshot.getImageDataUri();
                }""")
                image_bytes = base64.b64decode(png.split(',', 1)[1])
                image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
                background = image.getpixel((0, 0))
                center = image.crop((image.width // 4, image.height // 4,
                                     image.width * 3 // 4, image.height * 3 // 4))
                visible_pixels = sum(sum(abs(a - b) for a, b in zip(pixel, background)) > 25
                                     for pixel in center.getdata())
                show(f'分子库 {molecule} / {mode}',
                     len(active) == 1 and active[0]['type'] == style_types[mode]
                     and active[0]['objects'] > 0 and visible_pixels > 100,
                     str(active) + f' foreground pixels={visible_pixels}')
                if molecule in ('hydrogen', 'oxygen', 'nitrogen', 'chlorine', 'water', '1crn', 'nacl') and mode in ('ball-and-stick', 'cartoon'):
                    image.save(f'{SHOT}/library_{molecule}_{mode}.png')
            if 'cartoon' not in modes:
                show(f'分子库 {molecule} 禁用不适用的卡通', cartoon.is_disabled())

        ethanol = page.locator('.chem-library-card[data-id="ethanol"]')
        select_library(ethanol)
        initial_camera = frame.locator('body').evaluate(
            'window.__testLibraryViewer.plugin.canvas3d.camera.getSnapshot()')
        page.click('#chemViewSpin')
        frame.locator('body').evaluate('window.__testLibraryViewer.plugin.canvas3d.requestDraw(true)')
        moved = frame.locator('body').evaluate("""(_el, initial) => new Promise(resolve => {
          const viewer = window.__testLibraryViewer;
          const start = performance.now();
          function check() {
            const current = viewer.plugin.canvas3d.camera.getSnapshot();
            if (current.position.some((v, i) => Math.abs(v - initial.position[i]) > 0.01)) resolve(true);
            else if (performance.now() - start > 5000) resolve(false);
            else requestAnimationFrame(check);
          }
          check();
        })""", initial_camera)
        show('分子库自动旋转实际改变相机',
             moved and page.locator('#chemViewSpin').get_attribute('aria-pressed') == 'true')
        page.click('#chemViewReset')
        page.wait_for_function(
            "() => document.getElementById('chemViewStatus').textContent.includes('视角已重置')")
        reset_camera = frame.locator('body').evaluate(
            'window.__testLibraryViewer.plugin.canvas3d.camera.getSnapshot()')
        error = max(abs(a - b) for key in ('position', 'up', 'target')
                    for a, b in zip(initial_camera[key], reset_camera[key]))
        show('分子库重置恢复完整相机',
             error < 1e-5 and page.locator('#chemViewSpin').get_attribute('aria-pressed') == 'false',
             f'camera error={error:.6g}')
        page.screenshot(path=f'{SHOT}/02b_library.png', full_page=True)
        timings = []
        for cycle in range(2):
            for mode in ('spacefill', 'wireframe', 'ball-and-stick'):
                started = time.monotonic()
                page.select_option('#chemViewStyle', mode)
                page.wait_for_function("""style => {
                  const el = document.getElementById('chemViewStatus');
                  return el.dataset.style === style && el.dataset.state === 'ready';
                }""", arg=mode, timeout=10000)
                if cycle:
                    timings.append((time.monotonic() - started) * 1000)
        show('分子库缓存切换不重复生成表示', len(representation_state()) == 3)
        show('分子库缓存模式切换及时响应', max(timings) < 1800,
             'cached switch ms=' + ','.join(f'{t:.0f}' for t in timings))

        # 可视化化学：NaCl
        page.click('.chem-nav-item[data-tab="visual"]')
        page.locator('.chem-visual-card[data-slug="nacl"]').click()
        page.wait_for_timeout(3000)
        visual = page.frame_locator('#chemVisualFrame')
        try:
            visual.locator('canvas').first.wait_for(state='visible',
                                                    timeout=20000)
            show('可视化化学画布渲染', True)
        except Exception as exc:
            show('可视化化学画布渲染', False, str(exc)[:160])
        page.screenshot(path=f'{SHOT}/04_visual.png', full_page=True)

        # 调试：晶胞原点转换（左侧功能模块重影）
        page.click('#chemVisualBack')
        page.locator('.chem-visual-card[data-slug="crystal-origin"]').click()
        page.wait_for_timeout(3500)
        visual2 = page.frame_locator('#chemVisualFrame')
        try:
            visual2.locator('canvas').first.wait_for(state='visible',
                                                     timeout=20000)
        except Exception:
            pass
        print('[CRYSTAL-ORIGIN] switcher=',
              visual2.locator('#switcher').count(),
              'sidebars=', visual2.locator('#sidebar').count(),
              'cell-panel=', visual2.locator('#cell-panel').count())
        page.screenshot(path=f'{SHOT}/04b_crystal_origin.png', full_page=True)
        visual2.locator('#sw-toggle').click()
        page.wait_for_timeout(350)
        show('晶胞切换可收起', not visual2.locator('#sw-list').is_visible())
        visual2.locator('#sw-toggle').click()
        page.wait_for_timeout(350)
        show('晶胞切换可展开', visual2.locator('#sw-list').is_visible())
        for key in ('zns', 'caf2'):
            try:
                visual2.locator(f'.sw-item[data-key="{key}"]').click()
                page.wait_for_timeout(3500)
                stage = visual2.frame_locator('#stage')
                nested_canvas = stage.locator('canvas').count()
                engine = stage.locator('body').evaluate("""() => ({
                    three: typeof window.THREE,
                    orbit: !!(window.THREE && window.THREE.OrbitControls),
                    createStage: typeof window.createStage,
                    key: window.__YDNKEY || ''
                })""")
                print(f'[CRYSTAL {key}]', {
                    'state': visual2.locator('#bar-state').inner_text(),
                    'canvas': nested_canvas,
                    'engine': engine,
                })
                engine_ok = (engine['three'] == 'object' and engine['orbit']
                             and engine['key'] == key)
                if key == 'caf2':
                    engine_ok = engine_ok and engine['createStage'] == 'function'
                show(f'晶胞 {key.upper()} 3D 引擎启动', engine_ok and nested_canvas > 0,
                     f'canvas={nested_canvas} engine={engine}')
                page.screenshot(path=f'{SHOT}/04d_{key}.png', full_page=True)
            except Exception as exc:
                print(f'[CRYSTAL {key} FAIL]', exc)

        # 调试：周期表布局与元素信息面板
        page.click('#chemVisualBack')
        page.locator('.chem-visual-card[data-slug="periodic"]').click()
        page.wait_for_timeout(3000)
        periodic = page.frame_locator('#chemVisualFrame')
        try:
            periodic.locator('canvas, #ptable').first.wait_for(
                state='visible', timeout=15000)
        except Exception:
            pass
        print('[PERIODIC]', periodic.locator('body').evaluate("""() => {
          const r = s => { const el = document.querySelector(s);
            if (!el) return null; const b = el.getBoundingClientRect();
            return {x: Math.round(b.x), y: Math.round(b.y),
                    w: Math.round(b.width), h: Math.round(b.height),
                    disp: getComputedStyle(el).display,
                    vis: getComputedStyle(el).visibility};
          };
          return {innerW: innerWidth, innerH: innerHeight,
                  app: r('#app-container'), main: r('#main-row'),
                  ptable: r('#ptable'), info: r('#info-sidebar'),
                  detail: r('#detail-empty'),
                  bodyOverflow: getComputedStyle(document.body).overflow,
                  appOverflow: getComputedStyle(document.getElementById('app-container')).overflow};
        }"""))
        page.screenshot(path=f'{SHOT}/04c_periodic.png', full_page=True)
        try:
            periodic.locator('#tile-11').click()
            page.wait_for_timeout(800)
            print('[PERIODIC DETAIL]', periodic.locator('#detail-box').evaluate(
                """el => ({display: getComputedStyle(el).display,
                          text: (el.innerText || '').slice(0, 120)})"""))
        except Exception as exc:
            print('[PERIODIC DETAIL FAIL]', exc)
        page.click('#chemVisualBack')

        # 课堂嵌入：embed=1 无站点导航/页脚/AI
        page.set_viewport_size({'width': 1024, 'height': 600})
        page.goto('/chem-lab?embed=1')
        page.wait_for_selector('#chemLab', state='visible', timeout=20000)
        page.wait_for_timeout(5000)
        print('[EMBED LAYOUT]', page.evaluate("""() => {
          const r = s => { const el = document.querySelector(s);
            if (!el) return null; const b = el.getBoundingClientRect();
            return {h: Math.round(b.height), w: Math.round(b.width),
                    top: Math.round(b.top), bottom: Math.round(b.bottom)};
          };
          return {innerH: innerHeight, scrollH: document.documentElement.scrollHeight,
                  bodyH: document.body.getBoundingClientRect().height,
                  page: r('.chem-lab-page'), head: r('.chem-head'),
                  body: r('.chem-body'), main: r('.chem-main'),
                  nav: r('.chem-nav'), ketcher: r('.chem-ketcher-frame'),
                  viewer3d: r('#chem3dmol'), side: r('.chem-side')};
        }"""))
        embed_text = page.content()
        show('课堂嵌入极简壳',
             'navbar' not in embed_text or 'chem-embed' in embed_text)
        controls = ['.chem-head', '.chem-subtitle', '#chemHelpBtn', '#chemFullBtn',
                    '.chem-sketch-bar', '#chemSketchSample', '#chemSketchClear',
                    '#chemSketchDownload', '#chemSketchCopy', '#chemSketchFull']
        show('课堂完整标题与绘制工具可见',
             all(page.locator(selector).is_visible() for selector in controls))
        page.click('#chemHelpBtn')
        show('课堂帮助可以展开', page.locator('#chemHelp').is_visible())
        page.click('#chemHelpBtn')
        page.select_option('#chemSketchSample', 'CCO')
        page.wait_for_function(
            "() => document.getElementById('chem3dStatus').textContent.includes('C2H6O')",
            timeout=30000)
        show('课堂示例可以生成 3D', page.locator('#chem3dEmpty').is_hidden())
        embed_layout = page.evaluate("""() => {
          const el = document.querySelector('.chem-side');
          if (!el) return null; const b = el.getBoundingClientRect();
          return {w: Math.round(b.width), h: Math.round(b.height),
                  disp: getComputedStyle(el).display};
        }""")
        print('[EMBED SIDE]', embed_layout)
        show('课堂嵌入显示结构信息',
             bool(embed_layout) and embed_layout['w'] > 0
             and embed_layout['disp'] != 'none', str(embed_layout))
        show('嵌入无站点页脚', 'ITstudy V6.1.0' not in embed_text)
        page.screenshot(path=f'{SHOT}/06_embed.png', full_page=True)

        # 课堂舞台为嵌套 iframe：模拟 1100×520 的 stage 尺寸
        page.goto('/')
        page.evaluate("""() => {
          document.body.innerHTML =
            '<iframe id="stageWrap" src="/chem-lab?embed=1" ' +
            'style="width:1100px;height:520px;border:0;display:block"></iframe>';
        }""")
        page.wait_for_timeout(6000)
        wrap = page.frame_locator('#stageWrap')
        try:
            wrap.locator('#chemLab').wait_for(state='visible', timeout=15000)
            nested = wrap.locator('body').evaluate("""() => {
              const r = s => { const el = document.querySelector(s);
                if (!el) return null; const b = el.getBoundingClientRect();
                return {h: Math.round(b.height), top: Math.round(b.top),
                        bottom: Math.round(b.bottom)}; };
              return {innerH: innerHeight,
                      scrollH: document.documentElement.scrollHeight,
                      page: r('.chem-lab-page'), ketcher: r('.chem-ketcher-frame'),
                      viewer3d: r('#chem3dmol'), side: r('.chem-side')};
            }""")
            print('[NESTED EMBED]', nested)
            show('课堂嵌套尺寸完整',
                 nested['scrollH'] <= nested['innerH'] + 1
                 and nested['ketcher'] is not None
                 and nested['ketcher']['bottom'] <= nested['innerH'] + 1,
                 str(nested))
        except Exception as exc:
            show('课堂嵌套尺寸完整', False, str(exc)[:160])
        page.screenshot(path=f'{SHOT}/07_nested_embed.png', full_page=True)

        # 真实课堂入口：不是单独的 embed 页，保留外层章节树/课堂工具。
        # 独立教师上下文：学生会话与教师会话混在同一 Cookie 里时，
        # 角色判定会随会话字段叠加而变得不可预期。
        from app.models import Resource
        with app.app_context():
            chem_resource_id = Resource.query.filter_by(builtin_key='chem_lab').first().id
        tctx = browser.new_context(viewport={'width': 1400, 'height': 720},
                                   base_url=BASE)
        tpage = tctx.new_page()
        tpage.on('pageerror', lambda e: page_errors.append(str(e)))
        try:
            tpage.goto('/teacher/login')
            tpage.fill('input[name="username"]', TEACHER_NAME)
            mode = tpage.locator('#readonlyMode')
            if mode.count() and mode.is_enabled() and mode.is_checked():
                mode.uncheck()
            tpage.fill('input[name="password"]', PASSWORD)
            tpage.locator('form').filter(
                has=tpage.locator('input[name="username"]')).locator(
                'button[type="submit"]').click()
            tpage.wait_for_url('**/teacher/*', timeout=20000)
            tpage.goto(f'/study/lesson/{chem_resource_id}?mode=classroom')
            tpage.locator('.ch-item', has_text='化学仿真工作台').first.click()
            classroom = tpage.frame_locator('#linkFrame')
            try:
                classroom.locator('#chemLab').wait_for(state='visible', timeout=20000)
                classroom.frame_locator('#chemKetcherFrame').locator(
                    '.Ketcher-root').wait_for(state='visible', timeout=60000)
            except Exception:
                print('[CLASSROOM FRAMES]', [
                    (frame.url, frame.locator('#chemLab').count())
                    for frame in tpage.frames])
                print('[CLASSROOM LINK]', tpage.locator('#linkFrame').evaluate(
                    '(el) => ({src: el.src, cls: el.className})'))
                tpage.screenshot(path=f'{SHOT}/08_real_classroom_failed.png',
                                 full_page=True)
                raise
            show('真实课堂入口显示完整工作台',
                 all(classroom.locator(selector).is_visible() for selector in controls)
                 and classroom.locator('.chem-side').is_visible())
            classroom.locator('#chemSketchSample').select_option('O')
            classroom.locator('body').evaluate("""() => new Promise(resolve => {
              const start = performance.now();
              function check() {
                if (document.getElementById('chem3dStatus').textContent.includes('H2O')) resolve(true);
                else if (performance.now() - start > 30000) resolve(false);
                else requestAnimationFrame(check);
              }
              check();
            })""")
            show('真实课堂示例完成离线 3D',
                 'H2O' in classroom.locator('#chem3dStatus').inner_text())
            tpage.screenshot(path=f'{SHOT}/08_real_classroom.png', full_page=True)
        finally:
            tctx.close()

        # 教学深链与复制链接
        page.goto('/chem-lab?mol=water')
        page.wait_for_timeout(2500)
        show('深链分子加载',
             '水' in page.locator('#chemInfoTitle').inner_text(),
             page.locator('#chemInfoTitle').inner_text())
        show('复制教学链接按钮',
             page.locator('#chemVisualCopy').count() == 1)

        show('无页面 JS 异常', not page_errors, '; '.join(page_errors[:2]))
        show('无 CSP 违规', not csp_errors, '; '.join(csp_errors[:2]))
        show('无外部网络请求', not external_requests,
             '; '.join(external_requests[:3]))
        browser.close()
except Exception as exc:
    FAILED.append('浏览器运行异常')
    print('浏览器运行异常：', str(exc)[:600])
finally:
    cleanup()
    print('\n截图目录：', SHOT)
    print(f'通过 {len(CHECKED) - len(FAILED)}/{len(CHECKED)}')
    if FAILED:
        print('失败项：', FAILED)
        sys.exit(1)
    print('全部通过')
