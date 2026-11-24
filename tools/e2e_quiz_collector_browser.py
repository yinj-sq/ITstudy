# -*- coding: utf-8 -*-
"""采集 SDK 兼容性浏览器回归（按钮式自定义测验，2026-10-23）。

不启动 Flask：用本地 HTML + Playwright 拦截 /api/resource_quiz/submit，
验证 SDK 能从“可见结果区”读取分数/题数、采集按钮选项，并忽略隐藏证书占位。
"""
import json
import os
import pathlib
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_JS = ROOT / 'static' / 'sdk' / 'collector-base.js'
QUIZ_JS = ROOT / 'static' / 'sdk' / 'quiz-collector.js'

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>按钮式测验采集回归</title></head>
<body>
  <div id="quiz-container">
    <h4>问题 <span id="qnum">1</span>/2</h4>
    <button id="option-0" onclick="selectAnswer(0)">A. 选项一</button>
    <button id="option-1" onclick="selectAnswer(1)">B. 选项二</button>
  </div>
  <div id="test-result" style="display:none">
    <div>测试完成</div>
    <div id="total-questions">2</div>
    <div id="correct-count">0</div>
    <div id="accuracy">0%</div>
  </div>
  <div id="certificate" style="display:none">
    <div id="certificate-score">得分：100分</div>
  </div>
  <div id="name-input" style="display:none"></div>
  <script>
    var current = 1;
    function selectAnswer(i) {
      if (current === 1) {
        current = 2;
        document.getElementById('qnum').textContent = '2';
      } else {
        document.getElementById('quiz-container').innerHTML = '';
        document.getElementById('test-result').style.display = 'block';
      }
    }
  </script>
  <script>window.__INJECT_RESOURCE_ID__ = 6; window.__ITSTUDY_QUIZ_SOURCE_FILE__ = 'quiz/knn.html';</script>
  <script src="/static/sdk/collector-base.js"></script>
  <script src="/static/sdk/quiz-collector.js"></script>
</body></html>'''

HTML_DRY = HTML.replace(
    "<script>window.__INJECT_RESOURCE_ID__ = 6; window.__ITSTUDY_QUIZ_SOURCE_FILE__ = 'quiz/knn.html';</script>",
    "<script>window.__INJECT_RESOURCE_ID__ = 6; window.__ITSTUDY_QUIZ_SOURCE_FILE__ = 'quiz/knn.html';</script>\n"
    "  <script>window.__ITSTUDY_QUIZ_DRY_RUN__ = true;"
    " window.__ITSTUDY_QUIZ_REPORT_URL__ = '/teacher/resources/6/quiz-check/report/token123';"
    " window.__ITSTUDY_QUIZ_CSRF__ = 't';</script>")


captured = []
dry_captured = []
failed = []


def _capture(route):
    try:
        captured.append(json.loads(route.request.post_data or '{}'))
    except Exception:
        captured.append({})
    route.fulfill(status=200, content_type='application/json',
                  body='{"success": true}')


def _capture_dry(route):
    try:
        dry_captured.append(json.loads(route.request.post_data or '{}'))
    except Exception:
        dry_captured.append({})
    route.fulfill(status=200, content_type='application/json',
                  body='{"success": true}')


def check(name, ok, extra=''):
    print(('PASS' if ok else 'FAIL') + ' ' + name + ((' | ' + str(extra)) if extra else ''))
    if not ok:
        failed.append(name)


html_name = f'_collector_e2e_{os.getpid()}.html'
html_path = ROOT / 'data' / html_name
html_path.write_text(HTML, encoding='utf-8')
dry_path = ROOT / 'data' / f'_collector_dry_{os.getpid()}.html'
handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page()
        page.on('pageerror', lambda e: failed.append('pageerror: ' + str(e)))
        page.route(
            '**/api/resource_quiz/submit',
            lambda route: _capture(route))
        page.goto(f'{base}/data/{html_name}')
        page.locator('#option-0').click()
        page.wait_for_timeout(150)
        page.locator('#option-0').click()
        page.wait_for_timeout(900)

        dry_path.write_text(HTML_DRY, encoding='utf-8')
        dry_page = browser.new_page()
        dry_page.on('pageerror', lambda e: failed.append('dry pageerror: ' + str(e)))
        dry_page.route(
            '**/teacher/resources/6/quiz-check/report/token123',
            lambda route: _capture_dry(route))
        dry_page.goto(f'{base}/data/{dry_path.name}')
        dry_page.locator('#option-0').click()
        dry_page.wait_for_timeout(150)
        dry_page.locator('#option-0').click()
        dry_page.wait_for_timeout(900)
        browser.close()
finally:
    server.shutdown()
    server.server_close()
    for path in (html_path, dry_path):
        try:
            path.unlink()
        except OSError:
            pass

payload = captured[-1] if captured else {}
check('按钮式选项和结果区触发提交', bool(payload), len(captured))
check('隐藏证书的 100 分未被误采', payload.get('total_score') == 0,
      payload.get('total_score'))
check('满分归一为 100', payload.get('max_score') == 100, payload.get('max_score'))
check('正确数/总题数', payload.get('correct_count') == 0
      and payload.get('question_count') == 2,
      (payload.get('correct_count'), payload.get('question_count')))
check('按钮选项答案已采集',
      len(payload.get('answers') or {}) == 2 and
      (payload.get('answers') or {}).get('q1', '').startswith('A.'),
      payload.get('answers'))
check('提交携带来源文件', payload.get('source_file') == 'quiz/knn.html',
      payload.get('source_file'))

dry_payload = dry_captured[-1] if dry_captured else {}
check('模拟检测不写正式接口', len(captured) == 1, len(captured))
check('模拟检测上报抓取结果', bool(dry_payload), len(dry_captured))
check('模拟检测携带来源文件与答案',
      dry_payload.get('source_file') == 'quiz/knn.html' and
      len(dry_payload.get('answers') or {}) == 2,
      dry_payload)

print()
print('采集 SDK 浏览器回归：%s' % ('全部通过' if not failed else '%d 项失败：%s' % (len(failed), failed)))
sys.exit(1 if failed else 0)
