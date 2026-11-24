# -*- coding: utf-8 -*-
"""SPA 前端 API 路径与后端路由一致性检查（只读）

1) 提取 frontend/api/*.js 中 apiClient.<verb>('path') 的路径（自动补 baseURL）
2) 提取全部蓝图中注册的路由（含各自 url_prefix 与 <int:> 转换）
3) 比对：模板化的 <int:x> → 任意数字段

修复记录（2026-09-13）：此前只扫 app/blueprints/api*.py，且不给前端的
相对路径补 apiClient 的 baseURL（'/api'），拼接正则又要求两侧**都是**
字符串字面量 —— 三重局限导致 16 条路径被误报为「未匹配路由」。
经 Flask url_map 逐条核实，16 条**全部是真实存在的路由**。
"""
import re
import glob

# ── 1. 后端路由（全蓝图，非仅 api*.py）────────────────
# 两遍扫描：api_auth.py 等文件是**导入** api_bp（定义在 api.py），
# 单文件内查前缀会得到空串 → 路由全部漏配 /api。
bp_files = glob.glob('app/blueprints/*.py')
sources = {f: open(f, encoding='utf-8').read() for f in bp_files}

# 第一遍：蓝图变量名 → url_prefix（跨文件全局映射）
prefixes = {}
for src in sources.values():
    for m in re.finditer(
            r"(\w+)\s*=\s*Blueprint\((.+?)\)\s*\n", src, re.S):
        pfx = re.search(r"url_prefix\s*=\s*'([^']*)'", m.group(2))
        prefixes[m.group(1)] = pfx.group(1) if pfx else ''

# 第二遍：解析装饰器，补上所属蓝图的前缀
routes = set()
for src in sources.values():
    for m in re.finditer(r"@(\w+)\.route\('([^']+)'", src):
        r = prefixes.get(m.group(1), '') + m.group(2)
        r = re.sub(r'<int:[^>]+>', ':id', r)
        r = re.sub(r'<path:[^>]+>', ':path', r)
        r = re.sub(r'<[^>]+>', ':p', r)
        routes.add(r)
print('后端路由: %d 条（全蓝图 %d 个变量已定位前缀）'
      % (len(routes), len(prefixes)))

# ── 2. SPA 请求路径 ──────────────────────────────
API_BASE = '/api'   # frontend/api/client.js 的 baseURL
spa_paths = set()
for f in glob.glob('frontend/api/*.js'):
    src = open(f, encoding='utf-8').read()
    # 2.1 纯字面量：apiClient.get('/exams')
    #     (?!\s*\+) 排除 `'/trend/' + id` 这类拼接的**截断前缀**——
    #     它们由 2.2 正确解析为 '/trend/:id'，不收进来免得虚报一条。
    for m in re.findall(
            r"apiClient\.(?:get|post|put|delete|patch)\(\s*(['\"`])([^'\"`]*)\1"
            r"(?!\s*\+)", src):
        spa_paths.add(API_BASE + m[1])
    # 2.2 单字面量 + 变量：apiClient.get('/results/' + id)
    for m in re.findall(
            r"apiClient\.(?:get|post|put|delete|patch)\(\s*(['\"])([^'\"]*)\1\s*\+",
            src):
        spa_paths.add(API_BASE + m[1] + ':id')
    # 2.3 双字面量夹变量：apiClient.get('/a/' + id + '/b')
    for m in re.findall(
            r"apiClient\.(?:get|post|put|delete|patch)\(\s*(['\"])([^'\"]*)\1"
            r"\s*\+\s*\w+\s*\+\s*(['\"])([^'\"]*)\3", src):
        spa_paths.add(API_BASE + m[1] + ':id' + m[3])
    # 2.4 反引号模板：apiClient.get(`/a/${id}`)
    for m in re.findall(
            r"apiClient\.(?:get|post|put|delete|patch)\(\s*`([^`]*)`", src):
        t = re.sub(r'\$\{[^}]+\}', ':id', m)
        spa_paths.add(API_BASE + t)

# 模板里手写的绝对 API 路径（已含 /api，不再补前缀）
for tpl in glob.glob('templates/*.html'):
    src = open(tpl, encoding='utf-8').read()
    # 纯字面量（排除 '...' + id 的截断前缀，下面单独处理）
    for m in re.findall(
            r"(?:fetch|axios\.(?:get|post|put|delete))\(\s*(['\"])(/api/[^'\"]+)\1"
            r"(?!\s*\+)", src):
        spa_paths.add(m[1])
    # 字面量 + 变量拼路径
    for m in re.findall(
            r"(?:fetch|axios\.(?:get|post|put|delete))\(\s*(['\"])(/api/[^'\"]*)\1"
            r"\s*\+", src):
        spa_paths.add(m[1] + ':id')
    for m in re.findall(r"url:\s*(['\"])(/api/[^'\"]+)\1(?!\s*\+)", src):
        spa_paths.add(m[1])

print('SPA/模板请求路径: %d 条' % len(spa_paths))


def _matches(path):
    """路径是否命中某条后端路由（:id → 数字段，尾斜杠两侧均可省）。

    必须以**路由**为蓝本构图、拿 SPA 路径去匹配——反过来（旧写法）是拿
    SPA 路径构图、去匹配路由字符串，两边占位符形态不同（`[0-9]+` vs
    字面量 `:id`）恒不相等，等于该分支从未生效，全靠上面的精确相等兜底。
    `<path:x>` 可含斜杠，展开为 `.+`。
    """
    base = path.rstrip('/') or '/'
    for r in routes:
        esc = re.escape(r)
        for seg in (r'[0-9]+', r'[^/]+'):
            pat = '^' + esc.replace(':id', seg).replace(':path', '.+') + '/?$'
            if re.match(pat, base):
                return True
    return False


miss = [p for p in sorted(spa_paths) if p not in routes and not _matches(p)]
print('── 未匹配后端路由的路径 ──')
for m in miss:
    print('MISS:', m)
if not miss:
    print('（无）全部匹配')
