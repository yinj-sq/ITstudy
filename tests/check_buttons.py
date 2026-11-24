# -*- coding: utf-8 -*-
"""前端按钮/链接/API 调用 → Flask 路由存在性检测"""
import io
import os
import re
import sys

# 控制台可能是 GBK 代码页：报告里的 ❌ 等非 GBK 字符直接 print 会抛
# UnicodeEncodeError 中断脚本（此前跑到「路由不存在的引用」就崩）。
# 把 stdout 包成 UTF-8 写字节，永不因终端编码崩溃。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 钉隔离库：此前不设 DB_NAME → 解析成安装默认的生产库 itstudy，
# create_app() 会对生产库执行 create_all/migrate_db/create_db_indexes
# 并把缓存灌进生产 data/cache（与 check_page_buttons.py 同口径）
os.environ['DB_NAME'] = 'itstudy_btncheck'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_test')
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'
os.environ['DB_USER'] = 'postgres'
os.environ['DB_PASS'] = '@@'
os.environ['SECRET_KEY'] = 'btn-check-key'
sys.path.insert(0, os.getcwd())

from app import create_app

app = create_app()

# 收集 Flask 路由（静态路由 + 蓝图前缀展开）
url_map = set()
for rule in app.url_map.iter_rules():
    url_map.add(rule.rule)
# 同时记录 url_for 可解析的端点名
endpoints = set()
for rule in app.url_map.iter_rules():
    endpoints.add(rule.endpoint)

TEMPLATE_DIR = os.path.join(os.getcwd(), 'templates')
JS_DIRS = [os.path.join(os.getcwd(), 'static', 'js'),
           os.path.join(os.getcwd(), 'frontend')]

missing = []       # (来源, 上下文, URL)
checked = []       # (来源, URL)


def _segments(path):
    return [p for p in path.strip('/').split('/') if p]


def _match_parts(url_parts, rule_parts):
    """递归匹配；<path:...> 可吃掉任意多段（覆盖 /static/<path:filename>）。"""
    if not rule_parts:
        return not url_parts
    head, rest = rule_parts[0], rule_parts[1:]
    if head.startswith('<'):
        if head.startswith('<path:'):
            return any(_match_parts(url_parts[k:], rest)
                       for k in range(len(url_parts) + 1))
        return bool(url_parts) and _match_parts(url_parts[1:], rest)
    return bool(url_parts) and url_parts[0] == head and _match_parts(url_parts[1:], rest)


def url_matches(url, rule):
    """把模板中的 URL（可能带参数占位）与路由规则匹配"""
    if url in url_map:
        return True
    trailing = url.endswith('/')
    url_parts = _segments(url)
    rule_parts = _segments(rule)
    if _match_parts(url_parts, rule_parts):
        return True
    # 前端常见写法 fetch('/admin/exams/toggle/' + id)：URL 以 / 结尾，
    # 路由末尾是动态段。允许规则末尾的动态段尚缺参数值。
    if trailing:
        while rule_parts and rule_parts[-1].startswith('<'):
            rule_parts.pop()
        return bool(rule_parts) and _match_parts(url_parts, rule_parts)
    return False

def check_url(source, url):
    if not url or url.startswith(('http://', 'https://', '//', '#')):
        return
    # Jinja / JS 模板拼接（{{ id }}、${id}）不参与静态路由比对
    if any(token in url for token in ('{{', '{%', '${')):
        return
    url = url.split('#')[0].split('?')[0]
    if not url.startswith('/'):
        return
    checked.append((source, url))
    ok = any(url_matches(url, r) for r in url_map)
    if not ok:
        missing.append((source, url))

# ── 1. 扫描模板 ──
html_files = []
for root, _, files in os.walk(TEMPLATE_DIR):
    for f in files:
        if f.endswith('.html'):
            html_files.append(os.path.join(root, f))

btn_pat = re.compile(r'(?:href|action|data-url)\s*=\s*["\']([^"\']+)["\']')
fetch_pat = re.compile(r"""fetch\(\s*['"]([^'"]+)['"]""")
axios_pat = re.compile(r"""axios\.(?:get|post|put|delete)\(\s*['"]([^'"]+)['"]""")
jq_pat = re.compile(r"""[\$]\.(?:get|post|ajax)\(\s*['"]([^'"]+)['"]""")
xhr_pat = re.compile(r"""open\(\s*['"](?:GET|POST|PUT|DELETE)['"]\s*,\s*['"]([^'"]+)['"]""")
loc_pat = re.compile(r"""location\.(?:href|assign)\s*=\s*['"]([^'"]+)['"]""")
win_pat = re.compile(r"""window\.open\(\s*['"]([^'"]+)['"]""")

total_buttons = 0
for path in html_files:
    rel = os.path.relpath(path, TEMPLATE_DIR)
    try:
        content = open(path, encoding='utf-8').read()
    except Exception:
        continue
    # 按钮计数：button / a.btn / input[type=submit/button]
    btn_count = len(re.findall(r'<button\b', content, re.I)) + \
                len(re.findall(r'<a\b[^>]*class="[^"]*btn', content)) + \
                len(re.findall(r'<input\b[^>]*type="(?:submit|button)"', content, re.I))
    total_buttons += btn_count
    for m in btn_pat.finditer(content):
        check_url(f'{rel}(attr)', m.group(1))
    for m in fetch_pat.finditer(content):
        check_url(f'{rel}(fetch)', m.group(1))
    for m in axios_pat.finditer(content):
        check_url(f'{rel}(axios)', m.group(1))
    for m in jq_pat.finditer(content):
        check_url(f'{rel}(jquery)', m.group(1))
    for m in xhr_pat.finditer(content):
        check_url(f'{rel}(xhr)', m.group(1))
    for m in loc_pat.finditer(content):
        check_url(f'{rel}(location)', m.group(1))
    for m in win_pat.finditer(content):
        check_url(f'{rel}(window.open)', m.group(1))

# ── 2. 扫描前端 JS（frontend/ 与 static/js 内联引用）──
for base in JS_DIRS:
    if not os.path.isdir(base):
        continue
    for root, _, files in os.walk(base):
        for f in files:
            if not f.endswith('.js'):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, os.getcwd())
            try:
                content = open(path, encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for m in fetch_pat.finditer(content):
                check_url(f'{rel}(fetch)', m.group(1))
            for m in axios_pat.finditer(content):
                check_url(f'{rel}(axios)', m.group(1))
            for m in jq_pat.finditer(content):
                check_url(f'{rel}(jquery)', m.group(1))
            for m in xhr_pat.finditer(content):
                check_url(f'{rel}(xhr)', m.group(1))
            for m in loc_pat.finditer(content):
                check_url(f'{rel}(location)', m.group(1))

# ── 3. 检查 url_for 端点引用（模板里硬编码端点名的调用点）──
urlfor_pat = re.compile(r"""url_for\(\s*['"]([^'"]+)['"]""")
urlfor_missing = []
for path in html_files:
    rel = os.path.relpath(path, TEMPLATE_DIR)
    content = open(path, encoding='utf-8').read()
    for m in urlfor_pat.finditer(content):
        ep = m.group(1)
        if ep not in endpoints:
            urlfor_missing.append((rel, ep))

# ── 输出报告 ──
print(f'模板数: {len(html_files)}  |  页面按钮/提交控件总数: {total_buttons}')
print(f'检查的 URL/API 引用: {len(checked)}')
print(f'\n── 路由不存在的引用 ({len(missing)}) ──')
for src, url in sorted(set(missing)):
    print(f'  ❌ [{src}] {url}')
print(f'\n── url_for 端点不存在的引用 ({len(urlfor_missing)}) ──')
for src, ep in sorted(set(urlfor_missing)):
    print(f'  ❌ [{src}] url_for({ep!r})')
if not missing and not urlfor_missing:
    print('  (无)')

# 供 CI / 回归脚本判断：存在不存在的路由引用时返回非零
exit_code = 1 if (missing or urlfor_missing) else 0

# 隔离库用完即删：本脚本只做静态比对，create_app 的建表/种子数据不应沉积
try:
    from app.extensions import db
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    conn = psycopg2.connect(host='localhost', port=5432, user='postgres',
                            password='@@', dbname='postgres')
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute('DROP DATABASE IF EXISTS itstudy_btncheck WITH (FORCE)')
    cur.close()
    conn.close()
    print('测试库已清理')
except Exception as e:
    print('清理失败(忽略):', e)
sys.exit(exit_code)
