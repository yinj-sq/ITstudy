# -*- coding: utf-8 -*-
"""流程图 / 网络拓扑画板真实浏览器回归（static/lesson-tools/flow/index.html）。

覆盖 2026-11-11 修复：
1. overlay 层端口正常可见；
2. 已选中图形时悬停另一图形也显示它的端口，鼠标移到端口圆点上不消失；
3. 指针捕获 + 预览图形遮挡下落点识别仍能正确连线；
4. 切换 处理/判断/起止/文字 时同步填充色、描边色、文字对比色；
5. 拓扑图拖线到空白弹出设备选择（Esc / 点外取消不占撤销），流程图仍自动新建「下一步」。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_flow_tool_browser.py
纯静态页面，不需要数据库；用本地 HTTP 服务 + Edge 无头浏览器。
"""
import functools
import http.server
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLOW_DIR = ROOT / 'static' / 'lesson-tools' / 'flow'
ARTIFACTS = ROOT / 'data' / 'e2e_flow'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

errors = []
checks = []


def check(name, condition):
    checks.append(name)
    if not condition:
        raise AssertionError(name)
    print('PASS', name)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server():
    handler = functools.partial(QuietHandler, directory=str(FLOW_DIR))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def add_tool(page, label):
    """点左侧图形工具，关掉自动弹出的文字编辑器。"""
    page.evaluate(
        """(label) => {
          const d = [...document.querySelectorAll('#toolList .tool, #netList .tool')]
            .find(x => x.querySelector('.nm') && x.querySelector('.nm').textContent.trim() === label);
          if (!d) throw new Error('找不到工具：' + label);
          d.click();
        }""", label)
    page.locator('#textEditor').wait_for(state='visible')
    page.keyboard.press('Escape')
    page.locator('#textEditor').wait_for(state='hidden')


def node_ids(page):
    return page.evaluate(
        "() => [...document.querySelectorAll('#layerNodes g.node')].map(g => g.dataset.id)")


def node_box(page, node_id):
    loc = page.locator(f'#layerNodes g.node[data-id="{node_id}"]')
    for _ in range(20):
        box = loc.bounding_box()
        if box:
            return box
        page.wait_for_timeout(50)
    raise AssertionError('节点不可见：' + node_id)


def port_box(page, node_id, index=0):
    loc = page.locator(f'#layerOverlay .port[data-hid="{node_id}"]').nth(index)
    for _ in range(20):
        box = loc.bounding_box()
        if box:
            return box
        page.wait_for_timeout(50)
    raise AssertionError('端口不可见：' + node_id)


def center(box):
    return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2


def hover_node(page, node_id):
    page.mouse.move(*center(node_box(page, node_id)))
    page.wait_for_timeout(120)


def hist_steps(page):
    page.click('#btnHist')
    count = page.locator('#histPop li[data-jump]').count()
    page.click('#btnHist')
    return count


def clear_doc(page):
    page.click('#btnClear')
    page.click('#cfYes')
    page.wait_for_timeout(100)


def node_visual(page, node_id):
    return page.evaluate(
        """(id) => {
          const g = document.querySelector('#layerNodes g.node[data-id="' + id + '"]');
          const txt = g.querySelector('text');
          const sh = g.querySelector('.sh');
          return {
            text: txt ? txt.getAttribute('fill') : null,
            tag: sh ? sh.tagName.toLowerCase() : null,
            fill: sh ? sh.getAttribute('fill') : null,
            stroke: sh ? sh.getAttribute('stroke') : null,
          };
        }""", node_id)


def click_chip(page, label):
    page.evaluate(
        """(label) => {
          const b = [...document.querySelectorAll('#nodePanel button.chip')]
            .find(x => x.textContent.trim() === label);
          if (!b) throw new Error('找不到形状按钮：' + label);
          b.click();
        }""", label)


server = start_server()
base = f'http://127.0.0.1:{server.server_port}'
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/index.html')
        page.locator('#stage').wait_for()
        clear_doc(page)

        # ── 1/2：端口可见性 + 悬停优先 ──
        add_tool(page, '处理步骤')
        p1 = node_ids(page)[0]
        ports = page.locator('#layerOverlay .port')
        check('选中图形后 overlay 端口可见', ports.count() == 4 and
              page.locator('#layerOverlay .port').first.evaluate(
                  'el => getComputedStyle(el).opacity') == '1')

        add_tool(page, '判断条件')
        p2 = node_ids(page)[1]
        page.mouse.click(*center(node_box(page, p1)))       # 选中 P1
        hover_node(page, p2)
        hids = page.evaluate(
            "() => [...document.querySelectorAll('#layerOverlay .port')].map(p => p.dataset.hid)")
        check('已选中图形时悬停另一图形显示它的端口', len(hids) == 4 and set(hids) == {p2})

        page.mouse.move(*center(port_box(page, p2, 0)))     # 移到端口圆点上
        page.wait_for_timeout(200)
        hids = page.evaluate(
            "() => [...document.querySelectorAll('#layerOverlay .port')].map(p => p.dataset.hid)")
        check('鼠标停在端口上不因重绘消失', len(hids) == 4 and set(hids) == {p2})

        # ── 3：拖线到目标设备正确连线（指针捕获 + 预览遮挡） ──
        page.mouse.down()
        page.mouse.move(*center(node_box(page, p1)), steps=12)
        page.mouse.up()
        page.wait_for_timeout(120)
        check('拖线到目标设备建立连线且不误建图形',
              page.locator('#layerEdges g.edge').count() == 1 and len(node_ids(page)) == 2)

        # ── 4：切换形状同步配色 ──
        page.mouse.click(*center(node_box(page, p2)))
        click_chip(page, '文字')
        visual = node_visual(page, p2)
        check('切到「文字」：深色文字、无填充描边', visual['tag'] != 'path' and visual['text'] == '#1f2330')
        click_chip(page, '处理')
        visual = node_visual(page, p2)
        check('切到「处理」：同步填充/描边/白字',
              visual['tag'] == 'path' and visual['fill'] == '#2563eb' and
              visual['stroke'] == '#1d4ed8' and visual['text'] == '#ffffff')

        # ── 5a：流程图拖空白仍自动新建「下一步」 ──
        hover_node(page, p2)
        page.mouse.move(*center(port_box(page, p2, 0)))
        page.mouse.down()
        page.mouse.move(620, 760, steps=12)
        page.mouse.up()
        page.wait_for_timeout(150)
        nn = page.evaluate(
            """() => {
              const g = [...document.querySelectorAll('#layerNodes g.node')].pop();
              return { n: document.querySelectorAll('#layerNodes g.node').length,
                       text: g.querySelector('text') ? g.querySelector('text').textContent.trim() : '' };
            }""")
        check('流程图拖空白自动新建「下一步」', nn['n'] == 3 and '下一步' in nn['text'])
        page.keyboard.press('Escape')

        # ── 5b：拓扑图拖空白弹设备选择，取消不占撤销 ──
        page.reload()
        page.locator('#stage').wait_for()
        clear_doc(page)
        page.click('#netToggle')
        add_tool(page, '路由器 / 交换机')
        add_tool(page, '服务器')
        ids = node_ids(page)
        check('拓扑图前期就绪（两台网络设备）', len(ids) == 2)
        router = ids[0]
        steps_before = hist_steps(page)

        hover_node(page, router)
        page.mouse.move(*center(port_box(page, router, 0)))
        page.mouse.down()
        page.mouse.move(700, 740, steps=12)
        page.mouse.up()
        page.wait_for_timeout(150)
        picker = page.locator('.pop.devpick')
        check('拓扑图拖空白弹出设备选择且不生成处理步骤',
              picker.is_visible() and len(node_ids(page)) == 2)
        page.keyboard.press('Escape')
        page.wait_for_timeout(100)
        check('Esc 取消设备选择且不占撤销记录',
              page.locator('.pop.devpick').count() == 0 and hist_steps(page) == steps_before)

        hover_node(page, router)
        page.mouse.move(*center(port_box(page, router, 0)))
        page.mouse.down()
        page.mouse.move(700, 740, steps=12)
        page.mouse.up()
        page.wait_for_timeout(150)
        page.evaluate(
            """() => {
              const b = [...document.querySelectorAll('.pop.devpick .devopt')]
                .find(x => x.textContent.trim() === '服务器');
              if (!b) throw new Error('设备选择里没有「服务器」');
              b.click();
            }""")
        page.wait_for_timeout(150)
        placed = page.evaluate(
            """() => {
              const gs = [...document.querySelectorAll('#layerNodes g.node')];
              const g = gs[gs.length - 1];
              return { n: gs.length,
                       text: g.querySelector('text') ? g.querySelector('text').textContent.trim() : '',
                       edges: document.querySelectorAll('#layerEdges g.edge').length };
            }""")
        check('选中设备后就地放置并自动连线',
              placed['n'] == 3 and placed['edges'] == 1 and '服务器' in placed['text'])

        page.screenshot(path=str(ARTIFACTS / 'flow-topology.png'))
        check('全流程无页面 JavaScript 异常', not errors)
        browser.close()
finally:
    server.shutdown()
    server.server_close()

print(f'流程图/拓扑画板浏览器回归：{len(checks)} 项通过；截图目录：{ARTIFACTS}')
