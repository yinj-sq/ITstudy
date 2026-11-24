# -*- coding: utf-8 -*-
"""前端一致性静态检查（审查辅助脚本，只读）
1) onclick 调用的顶层函数是否在模板脚本中定义
2) getElementById 字面量引用是否匹配 id= 定义
3) fetch/ajax 字面量 URL 是否有反斜杠/空路径等明显错误
"""
import re
import glob
import os

issues = []
for tpl in sorted(glob.glob('templates/*.html')):
    src = open(tpl, encoding='utf-8').read()
    name = os.path.basename(tpl)
    funcs_defined = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)\s*\(', src))
    # 挂到 window 的顶层函数（window.foo = function / window.foo = (...) =>）：
    # survey_editor.html 的 syncCard/removeCard 即此写法，此前被误报未定义
    funcs_defined |= set(re.findall(
        r'window\.([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function|\()', src))
    for call in re.findall(r'on(?:click|change|submit|input|keyup)="([A-Za-z_$][\w$]*)\s*\(', src):
        if call not in funcs_defined:
            issues.append(f'[{name}] onclick 调用未定义函数: {call}()')
    ids_defined = set(re.findall(r'id="([\w\-]+)"', src))
    # 动态注入的元素 id 一并计入：`el.id = 'X'` / `setAttribute('id','X')`。
    # 此前只认静态 id="..."，study_link.html 里「先查 id 再注入并设置该 id」
    # 的防重复注入写法被误报为「引用不存在的 id」。
    ids_defined |= set(re.findall(r'\.id\s*=\s*["\']([\w\-]+)["\']', src))
    ids_defined |= set(re.findall(r'setAttribute\(\s*["\']id["\']\s*,\s*["\']([\w\-]+)["\']', src))
    for ref in re.findall(r'getElementById\(["\']([\w\-]+)["\']\)', src):
        if ref not in ids_defined and '{{' not in ref:
            issues.append(f'[{name}] getElementById 引用不存在的 id: {ref}')
    for u in re.findall(r'(?:fetch|axios\.(?:get|post|put|delete))\(\s*["\']([^"\']+)["\']', src):
        if '\\' in u or u == '' or u == '/':
            issues.append(f'[{name}] 可疑 URL: {u}')

for i in issues:
    print(i)
print('--- 共 %d 条问题 ---' % len(issues) if issues else '--- 未发现 onclick/id 不一致 ---')