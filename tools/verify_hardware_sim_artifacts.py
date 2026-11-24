# -*- coding: utf-8 -*-
"""硬件仿真静态产物校验 / SHA256 清单生成。

第三方或发布前可直接运行，不依赖 Flask / 数据库：

    venv/Scripts/python.exe tools/verify_hardware_sim_artifacts.py
    venv/Scripts/python.exe tools/verify_hardware_sim_artifacts.py --write-manifest

校验项：
- 两个仿真入口、固件/参考手册完整
- 无 *.map、无 Google Fonts 外部引用
- 掌控板发布版 DEFAULT_CREDS 全空
- 第三方 bundle 不引用 ITstudy /api/、不读 document.cookie 或父窗口 DOM
- 许可证/第三方声明齐全
- MANIFEST.sha256 与当前文件一致
"""
import argparse
import hashlib
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parent.parent
HW = ROOT / 'static' / 'hardware-sim'
MM = HW / 'mmake'
ESP = HW / 'esp32-s3'
MANIFEST = HW / 'MANIFEST.sha256'

REQUIRED_FILES = [
    MM / 'index.html',
    MM / 'js' / 'store.js',
    MM / 'js' / 'xfyun.js',
    MM / 'vendor' / 'blockly' / 'blockly_compressed.js',
    MM / 'vendor' / 'blockly' / 'blocks_compressed.js',
    MM / 'vendor' / 'blockly' / 'javascript_compressed.js',
    MM / 'vendor' / 'blockly' / 'python_compressed.js',
    MM / 'vendor' / 'blockly' / 'msg' / 'zh-hans.js',
    MM / 'LICENSE',
    ESP / 'index.html',
    ESP / 'LICENSE',
    ESP / 'firmware' / 'index.json',
    ESP / 'reference' / 'index.json',
    ESP / 'fonts' / 'fonts.css',
    ESP / 'fonts' / 'OFL.txt',
    HW / 'THIRD_PARTY_NOTICES.txt',
]

FORBIDDEN_BUNDLE_PATTERNS = [
    (re.compile(r"""['"]/api/"""), '引用 ITstudy /api/ 路径'),
    (re.compile(r'document\.cookie'), '读取 document.cookie'),
    (re.compile(r'(?:parent|top)\.document'), '访问父窗口 DOM'),
]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def artifact_files():
    for p in sorted(HW.rglob('*')):
        if p.is_file() and p.name != MANIFEST.name:
            yield p


def check_credentials(errors):
    src = (MM / 'js' / 'xfyun.js').read_text(encoding='utf-8-sig')
    m = re.search(r'var DEFAULT_CREDS = \{[\s\S]*?\n  \};', src)
    if not m:
        errors.append('掌控板 DEFAULT_CREDS 块未找到')
        return
    if any(v != '' for v in re.findall(r"'([^']*)'", m.group(0))):
        errors.append('掌控板 DEFAULT_CREDS 仍含非空字符串')
    if re.search(r"(?:apiKey|apiSecret|appId)\s*:\s*'[^']+'", src):
        errors.append('掌控板 xfyun.js 仍含非空凭据字面量')


def check_bundles(errors):
    scanned = 0
    for p in list(HW.rglob('*.js')) + list(HW.rglob('*.html')):
        text = p.read_text(encoding='utf-8', errors='ignore')
        scanned += 1
        for pattern, label in FORBIDDEN_BUNDLE_PATTERNS:
            if pattern.search(text):
                errors.append(f'{p.relative_to(HW)}: {label}')
    print(f'  扫描第三方 bundle: {scanned} 个文件')


def check_fonts(errors):
    html = (ESP / 'index.html').read_text(encoding='utf-8')
    if 'fonts.googleapis.com' in html or 'fonts.gstatic.com' in html:
        errors.append('ESP32 index.html 仍引用 Google Fonts')
    for text_file in list(ESP.rglob('*.css')) + list(ESP.rglob('*.html')):
        if 'fonts.googleapis.com' in text_file.read_text(encoding='utf-8', errors='ignore'):
            errors.append(f'{text_file.relative_to(HW)} 仍引用 Google Fonts')


def check_manifest(errors):
    if not MANIFEST.is_file():
        errors.append('MANIFEST.sha256 不存在（先运行 --write-manifest）')
        return
    seen = set()
    for line in MANIFEST.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        path = HW / rel.strip()
        seen.add(rel.strip())
        if not path.is_file():
            errors.append(f'清单文件缺失: {rel}')
        elif sha256(path) != digest:
            errors.append(f'清单哈希不一致: {rel}')
    for p in artifact_files():
        rel = p.relative_to(HW).as_posix()
        if rel not in seen:
            errors.append(f'清单未收录: {rel}')


def write_manifest():
    lines = [f'{sha256(p)}  {p.relative_to(HW).as_posix()}' for p in artifact_files()]
    MANIFEST.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'  已写入 {MANIFEST.relative_to(ROOT)}：{len(lines)} 个文件')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-manifest', action='store_true',
                        help='重新生成 MANIFEST.sha256')
    args = parser.parse_args()

    if not HW.is_dir():
        print(f'错误：{HW} 不存在')
        return 1

    errors = []
    for p in REQUIRED_FILES:
        if not p.is_file():
            errors.append(f'缺少文件: {p.relative_to(ROOT)}')
    if list(ESP.rglob('*.map')):
        errors.append('ESP32 产物仍含 *.map')
    check_credentials(errors)
    check_bundles(errors)
    check_fonts(errors)

    if args.write_manifest:
        write_manifest()
    else:
        check_manifest(errors)

    if errors:
        print('校验失败：')
        for e in errors:
            print('  -', e)
        return 1
    print('校验通过：入口/许可证/凭据/外部引用/清单均正常')
    return 0


if __name__ == '__main__':
    sys.exit(main())
