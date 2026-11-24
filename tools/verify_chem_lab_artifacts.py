# -*- coding: utf-8 -*-
"""校验化学仿真静态产物：入口、许可证、外部引用、API 引用与 SHA256 清单。

运行：venv/Scripts/python.exe tools/verify_chem_lab_artifacts.py
"""
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
CHEM = os.path.join(BASE, 'static', 'chem-lab')
MOL = os.path.join(CHEM, 'molecules')
VISUAL = os.path.join(CHEM, 'visual-chem')
MANIFEST = os.path.join(CHEM, 'MANIFEST.sha256')

FAILED = []


def check(name, ok, detail=''):
    print(('✓' if ok else '✗'), name, detail)
    if not ok:
        FAILED.append(name)


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def text(path):
    return read(path).decode('utf-8', errors='replace')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    required = [
        'viewer.html', 'js/viewer-app.js', 'THIRD_PARTY_NOTICES.md',
        'LICENSE-MOLVIEW', 'vendor/molstar/molstar.js',
        'vendor/molstar/molstar.css', 'vendor/molstar/LICENSE',
        'vendor/3dmol/3Dmol-min.js', 'vendor/3dmol/LICENSE',
        'vendor/3dmol/3Dmol-min.js.LICENSE.txt',
        'ketcher/index.html',
        'molecules/catalog.json',
    ]
    for rel in required:
        check(f'入口存在 {rel}', os.path.isfile(os.path.join(CHEM, rel)))

    ketcher_html = os.path.join(CHEM, 'ketcher', 'index.html')
    if os.path.isfile(ketcher_html):
        body = text(ketcher_html)
        check('Ketcher 仅加载本地资源',
              '/static/chem-lab/ketcher/' in body
              and 'http://' not in body and 'https://' not in body)
        assets = os.listdir(os.path.join(CHEM, 'ketcher', 'assets'))
        check('Ketcher 构建产物齐全',
              any(name.startswith('index-') and name.endswith('.js')
                  for name in assets)
              and any('conformer.worker' in name and name.endswith('.js')
                      for name in assets))
    check('无 MolDraw 在线引用',
          'moldraw' not in text(os.path.join(CHEM, 'THIRD_PARTY_NOTICES.md')).lower())

    # 可视化化学 21 个入口
    with open(os.path.join(MOL, 'catalog.json'), encoding='utf-8') as f:
        catalog = json.load(f)
    check('分子库 ≥ 27 项', len(catalog) >= 27, str(len(catalog)))
    check('分子库文件齐全', all(
        os.path.isfile(os.path.join(MOL, c['file'])) for c in catalog))

    from app.blueprints.chem_lab import VISUAL_PAGES
    check('可视化化学入口 21 个', len(VISUAL_PAGES) == 21,
          str(len(VISUAL_PAGES)))
    check('可视化化学文件齐全', all(
        os.path.isfile(os.path.join(VISUAL, p['file']))
        for p in VISUAL_PAGES.values()))

    # 外部 script/link 引用
    external = []
    for root, _dirs, files in os.walk(VISUAL):
        for name in files:
            if not name.endswith('.html'):
                continue
            body = text(os.path.join(root, name))
            external += re.findall(
                r'<script[^>]+src=["\']https?://[^"\']+', body, re.I)
            external += re.findall(
                r'<link[^>]+href=["\']https?://[^"\']+', body, re.I)
    check('可视化化学无外部 script/link', not external,
          str(external[:3]))

    # 运行期不应出现的同源 API / Cookie 访问
    forbidden = ['/api/', 'document.cookie', 'parent.document',
                 'top.document']
    hits = []
    for root, _dirs, files in os.walk(CHEM):
        for name in files:
            if not name.endswith(('.js', '.html')):
                continue
            path = os.path.join(root, name)
            rel_path = os.path.relpath(path, CHEM).replace(os.sep, '/')
            if (rel_path.startswith(('vendor/', 'ketcher/'))
                    or path.endswith('viewer-app.js')):
                continue
            body = text(path)
            for token in forbidden:
                if token in body:
                    hits.append((os.path.relpath(path, CHEM), token))
    check('无同源 API/Cookie 引用', not hits, str(hits[:5]))

    # 无 api.php / 原站返回脚本
    leftovers = []
    for root, _dirs, files in os.walk(VISUAL):
        for name in files:
            if name.endswith('.html'):
                body = text(os.path.join(root, name))
                for token in ('api.php', 'back-button.js', '_capture.js',
                              '版权所有', '寻微之路'):
                    if token in body:
                        leftovers.append(
                            (os.path.relpath(os.path.join(root, name), CHEM),
                             token))
    check('可视化化学无原站残留', not leftovers, str(leftovers[:5]))

    # vendor SHA256 清单一致性
    sums_path = os.path.join(CHEM, 'vendor', 'SHA256SUMS')
    if os.path.isfile(sums_path):
        bad = []
        with open(sums_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                digest, rel = line.split(' *', 1)
                path = os.path.join(CHEM, 'vendor', rel)
                if not os.path.isfile(path) or sha256(path) != digest:
                    bad.append(rel)
        check('vendor SHA256 一致', not bad, str(bad[:5]))

    # 生成全量 MANIFEST（排除 .gz 与自身）
    entries = []
    for root, _dirs, files in os.walk(CHEM):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, CHEM).replace(os.sep, '/')
            if rel.endswith('.gz') or rel == 'MANIFEST.sha256':
                continue
            entries.append(f'{sha256(path)}  {rel}')
    entries.sort(key=lambda x: x.split('  ', 1)[1])
    with open(MANIFEST, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(entries) + '\n')
    check('MANIFEST 生成', len(entries) > 50, f'{len(entries)} 个文件')

    print(f'\n结果：{"全部通过" if not FAILED else "失败 " + ", ".join(FAILED)}')
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
