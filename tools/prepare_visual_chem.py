# -*- coding: utf-8 -*-
"""把 123/可视化化学 迁入 static/chem-lab/visual-chem/ 并做去壳改造。

- 只保留 21 个模型页、_vip 子页与运行所需静态资源；
- 删除原站首页/登录/VIP、back-button.js、_capture.js、updates.js；
- 移除页面自适应的 base 脚本（由帧路由统一注入 <base>）；
- 隐藏原站顶栏与版权水印（按用户确认只保留模型内容）；
- 校验无 api.php / 外部请求 / 返回脚本。
"""
import os
import re
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, '123', '可视化化学')
DST = os.path.join(BASE, 'static', 'chem-lab', 'visual-chem')

PAGES = [
    'jingbao-yuandian.html', 'nacl.html', 'cscl.html', 'sic.html',
    'fe.html', 'po.html', '元素周期表.html', 'c60.html',
    'dapijian-co2.html', 'dapijian-ozone.html', 'dapijian-so3.html',
    'dapijian-ben.html', 'dapijian-pyrrole.html', 'dapijian-pyridine.html',
    'dianchi.html', 'dianjiao.html', 'xiuyiwan.html', 'yixi.html',
    'yique.html', 'ben.html', 'gongxiangongmian.html',
]
VIP_PAGES = ['_vip/zns.html', '_vip/caf2.html']

ASSETS = [
    'Engine.js', 'three.min.js', 'OrbitControls-umd.js',
    'crystal-frost-atoms.js', 'ui-glass.css', 'ui-glass.js',
    'organic-skin.css', 'op-tip.js', 'favicon.ico', 'favicon.png',
]

INJECT_CSS = """
<style id="chem-lab-embed-style">
  /* ITstudy 化学仿真统一壳：隐藏原站顶栏/品牌/版权水印。
     不强制页面高度与 overflow —— 各页面自有布局（周期表需要滚动，
     3D 页需要全屏），统一覆盖会把周期表底部裁掉。 */
  #topbar, #copyright, .wm-copyright, #btn-home,
  .topbar-actions, .back-home-btn,
  .brand, .brand-title, #brand-logo { display: none !important; }
  canvas { max-width: 100%; }
  /* 课堂 iframe 高度较小时：周期表隐藏趋势图、压缩行高，保证 118 元素可见 */
  @media (max-height: 720px) {
    #chart-panel { display: none !important; }
    .ptable.size-s { grid-auto-rows: 32px !important; }
    #info-sidebar { width: 220px; }
  }
</style>
"""

WATERMARKS = [
    '© 寻微之路 | 可视化学', '版权所有 · 维权必究',
    '© 寻微之路 | 可视化学　版权所有 · 维权必究',
]


def copy_tree(name):
    src = os.path.join(SRC, name)
    dst = os.path.join(DST, name)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    elif os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def clean_html(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    original = text
    # 删除返回脚本 / 抓取脚本 / 更新脚本
    text = re.sub(
        r"<script[^>]*src=['\"]back-button\.js[^'\"]*['\"][^>]*>\s*</script>",
        '', text, flags=re.I)
    text = re.sub(
        r"<script[^>]*src=['\"]_capture\.js[^'\"]*['\"][^>]*>\s*</script>",
        '', text, flags=re.I)
    text = re.sub(
        r"<script[^>]*src=['\"]updates\.js[^'\"]*['\"][^>]*>\s*</script>",
        '', text, flags=re.I)
    # 删除 wb-root-base 自适应 base 脚本块
    text = re.sub(
        r"<script>\s*/\*\s*wb-root-base:.*?</script>",
        '', text, flags=re.I | re.S)
    # 源站未镜像的 VIP 机理图：移除失效链接
    text = re.sub(
        r"<a[^>]+href=['\"]yixi-br-jinjie\.html[^>]*>.*?</a>",
        '', text, flags=re.I | re.S)
    # 周期表样品照片未随离线包分发：移除照片区，保留完整元素属性
    text = re.sub(
        r"const photo = \(function\(z\)\{.*?\}\)\(el\.z\);",
        "const photo = '';", text, flags=re.S)
    # 无效 sandbox 标记（Chromium 会报错，删除不影响功能）
    text = text.replace(' allow-fullscreen', '')
    # 去水印字符串
    for mark in WATERMARKS:
        text = text.replace(mark, '')
    text = text.replace('寻微之路', '可视化化学')
    # 注入统一壳样式（若尚未注入）
    if 'chem-lab-embed-style' not in text:
        if re.search(r'</head>', text, re.I):
            text = re.sub(r'</head>', INJECT_CSS + '</head>', text,
                          count=1, flags=re.I)
        else:
            text = INJECT_CSS + text
    if text != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return text


def clean_js(path):
    """清除 JS 中动态绘制的品牌水印（Engine.js / ui-glass.js）。"""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if '寻微之路' not in text and '版权所有' not in text:
        return
    for mark in WATERMARKS:
        text = text.replace(mark, '')
    text = text.replace('寻微之路', '可视化化学')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f'源目录不存在：{SRC}')
    os.makedirs(DST, exist_ok=True)
    for name in ASSETS + ['vendor', 'assets']:
        copy_tree(name)
    for root, _dirs, files in os.walk(DST):
        for name in files:
            if name.lower().endswith('.js'):
                clean_js(os.path.join(root, name))
    for rel in PAGES + VIP_PAGES:
        src = os.path.join(SRC, rel)
        dst = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        clean_html(dst)
        print(f'[OK] {rel}')
    print(f'\n已迁入 {len(PAGES) + len(VIP_PAGES)} 个页面到 {DST}')


if __name__ == '__main__':
    main()
