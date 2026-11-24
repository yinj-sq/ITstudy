# -*- coding: utf-8 -*-
"""PPTist 构建产物微创补丁：暴露内部 importPPTXFile 供 embed 胶水调用。

锚点：粘贴钩子组件的解构处（随编辑器必然挂载），在其后注入
window.__pptistAPI = {importPPTXFile, importSpecificFile}。
幂等：已打补丁则跳过；打补丁前备份 .bak。
"""
import os
import shutil
import sys

TARGET = os.path.join('static', 'pptist', 'assets', 'index-B0P34-pG.js')
ANCHOR = '{importSpecificFile:r,importPPTXFile:a}=_5e();return{pasteDataTransfer:i=>{'
PATCHED = ('{importSpecificFile:r,importPPTXFile:a}=_5e();'
           'window.__pptistAPI={importPPTXFile:a,importSpecificFile:r};'
           'return{pasteDataTransfer:i=>{')

src = open(TARGET, encoding='utf-8').read()
if 'window.__pptistAPI' in src:
    print('已打补丁，跳过')
    sys.exit(0)
cnt = src.count(ANCHOR)
print('锚点出现次数:', cnt)
if cnt != 1:
    print('锚点不唯一/未找到，中止（构建产物可能已更换，需重新定位）')
    sys.exit(1)

shutil.copy2(TARGET, TARGET + '.bak')
out = src.replace(ANCHOR, PATCHED)
assert out.count('window.__pptistAPI') == 1
with open(TARGET, 'w', encoding='utf-8', newline='') as f:
    f.write(out)
print('补丁完成，备份:', TARGET + '.bak')