# -*- coding: utf-8 -*-
"""构建化学仿真的本地分子库（构建期执行，运行时离线）。

数据源：
- 小分子/有机物：NCI CIR（名称 -> 3D SDF）
- 蛋白质：RCSB PDB 公共数据
- 晶体：脚本生成简化晶胞团簇（XYZ）

产物：
- static/chem-lab/molecules/{small,organic,proteins,crystals}/
- static/chem-lab/molecules/catalog.json
"""
import json
import os
import time
import urllib.parse

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHEM = os.path.join(BASE, 'static', 'chem-lab')
MOL = os.path.join(CHEM, 'molecules')
CIR = 'https://cactus.nci.nih.gov/chemical/structure'
RCSB = 'https://files.rcsb.org/download'
HEADERS = {'User-Agent': 'ITstudy-ChemLab-Build/6.1'}

# (id, 中文名, 化学式, CIR 查询名, 教材位置, 观察要点)
LIBRARY = [
    ('hydrogen', '氢气', 'H₂', '[H][H]', '必修第一册 · 物质分类', '双原子分子，键长最短的气体之一'),
    ('oxygen', '氧气', 'O₂', 'O=O', '必修第一册 · 物质分类', '双键结构，支持燃烧'),
    ('nitrogen', '氮气', 'N₂', 'N#N', '必修第一册 · 物质分类', '三键结构，化学性质稳定'),
    ('chlorine', '氯气', 'Cl₂', 'ClCl', '必修第一册 · 卤素', '黄绿色气体，双原子分子'),
    ('hydrogen-chloride', '氯化氢', 'HCl', 'hydrogen chloride', '必修第一册 · 卤素', '极性共价键，溶于水成盐酸'),
    ('water', '水', 'H₂O', 'water', '必修第一册 · 物质结构', 'V 形分子，键角约 104.5°'),
    ('carbon-dioxide', '二氧化碳', 'CO₂', 'carbon dioxide', '必修第一册 · 碳族', '直线形分子，两个 C=O 键'),
    ('ammonia', '氨', 'NH₃', 'ammonia', '必修第二册 · 氮族', '三角锥形，键角约 107°'),
    ('methane', '甲烷', 'CH₄', 'methane', '必修第二册 · 有机', '正四面体，键角 109.5°'),
    ('sulfur-dioxide', '二氧化硫', 'SO₂', 'sulfur dioxide', '必修第二册 · 硫', 'V 形分子，极性'),
    ('ethylene', '乙烯', 'C₂H₄', 'ethylene', '必修第二册 · 有机', '平面结构，C=C 双键'),
    ('acetylene', '乙炔', 'C₂H₂', 'acetylene', '必修第二册 · 有机', '直线形，C≡C 三键'),
    ('benzene', '苯', 'C₆H₆', 'benzene', '必修第二册 · 有机', '平面正六边形，离域 π 键'),
    ('ethanol', '乙醇', 'C₂H₅OH', 'ethanol', '必修第二册 · 有机', '含羟基，分子间氢键'),
    ('acetic-acid', '乙酸', 'CH₃COOH', 'acetic acid', '必修第二册 · 有机', '羧基结构，酸性'),
    ('glucose', '葡萄糖', 'C₆H₁₂O₆', 'glucose', '必修第二册 · 有机', '多羟基醛，环状结构'),
]

PROTEINS = [
    ('1crn', '1CRN 蛋白质', '1CRN', '蛋白质二级结构：α 螺旋与 β 折叠'),
    ('1bna', '1BNA DNA 片段', '1BNA', 'DNA 双螺旋与碱基配对'),
    ('1hho', '1HHO 血红蛋白', '1HHO', '四聚体与血红素辅基'),
    ('4ins', '4INS 胰岛素', '4INS', '二硫键与激素蛋白结构'),
]

# 预置检索缓存（中文名, 英文查询名, 化学式, 别名）
def fetch_cir(query, timeout=30):
    url = f"{CIR}/{urllib.parse.quote(query, safe='')}/sdf?get3d=true"
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    if 'V2000' not in text and 'V3000' not in text:
        raise ValueError('not a molfile')
    return text


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_text(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def gen_xyz(atoms, comment):
    lines = [str(len(atoms)), comment]
    for symbol, x, y, z in atoms:
        lines.append(f'{symbol} {x:.4f} {y:.4f} {z:.4f}')
    return '\n'.join(lines) + '\n'


def crystals():
    """生成晶胞团簇（示意）XYZ。"""
    out = []

    # NaCl：3×3×3 交替格点，Na-Cl 距离 2.82 Å
    atoms = []
    for i in range(3):
        for j in range(3):
            for k in range(3):
                atoms.append(('Na' if (i + j + k) % 2 == 0 else 'Cl',
                              i * 2.82, j * 2.82, k * 2.82))
    out.append(('nacl', '氯化钠晶胞团簇', 'NaCl', 'crystals/nacl.xyz',
                '面心立方；Na⁺ 与 Cl⁻ 的 6 配位', atoms))

    # CsCl：2×2×2 晶胞，Cs 角点 + Cl 体心
    atoms = []
    a = 4.12
    for i in range(3):
        for j in range(3):
            for k in range(3):
                atoms.append(('Cs', i * a, j * a, k * a))
    for i in range(2):
        for j in range(2):
            for k in range(2):
                atoms.append(('Cl', (i + 0.5) * a, (j + 0.5) * a,
                              (k + 0.5) * a))
    out.append(('cscl', '氯化铯晶胞团簇', 'CsCl', 'crystals/cscl.xyz',
                '体心立方；Cs⁺ 的 8 配位', atoms))

    # 金刚石：2×2×2 超胞
    atoms = []
    a = 3.57
    basis = [(0, 0, 0), (0, 0.5, 0.5), (0.5, 0, 0.5), (0.5, 0.5, 0),
             (0.25, 0.25, 0.25), (0.25, 0.75, 0.75),
             (0.75, 0.25, 0.75), (0.75, 0.75, 0.25)]
    for i in range(2):
        for j in range(2):
            for k in range(2):
                for bx, by, bz in basis:
                    atoms.append(('C', (i + bx) * a, (j + by) * a,
                                  (k + bz) * a))
    out.append(('diamond', '金刚石晶胞团簇', 'C', 'crystals/diamond.xyz',
                '每个碳原子 4 配位，sp³ 杂化', atoms))

    # 石墨：两层六角网格（示意）
    atoms = []
    dh = 1.42
    for layer in range(2):
        z = layer * 3.35
        for i in range(-2, 3):
            for j in range(-2, 3):
                x = i * dh * 1.5
                y = j * dh * 1.732 + (i % 2) * dh * 0.866
                atoms.append(('C', x, y, z))
    out.append(('graphite', '石墨层状结构（示意）', 'C', 'crystals/graphite.xyz',
                '层内共价键、层间范德华力', atoms))

    # 铜 fcc：2×2×2 超胞
    atoms = []
    a = 3.61
    basis = [(0, 0, 0), (0, 0.5, 0.5), (0.5, 0, 0.5), (0.5, 0.5, 0)]
    for i in range(2):
        for j in range(2):
            for k in range(2):
                for bx, by, bz in basis:
                    atoms.append(('Cu', (i + bx) * a, (j + by) * a,
                                  (k + bz) * a))
    out.append(('copper', '铜的面心立方晶胞', 'Cu', 'crystals/copper.xyz',
                '面心立方堆积，配位数 12', atoms))

    # 二氧化硅（β-方石英简化）：Si 金刚石位置 + O 中点
    atoms = []
    a = 7.16
    si = []
    basis = [(0, 0, 0), (0, 0.5, 0.5), (0.5, 0, 0.5), (0.5, 0.5, 0),
             (0.25, 0.25, 0.25), (0.25, 0.75, 0.75),
             (0.75, 0.25, 0.75), (0.75, 0.75, 0.25)]
    for bx, by, bz in basis:
        si.append((bx * a, by * a, bz * a))
        atoms.append(('Si', bx * a, by * a, bz * a))
    # O 放在 Si-Si 中点（仅连接距离 < 4 Å 的对）
    for idx, (x1, y1, z1) in enumerate(si):
        for x2, y2, z2 in si[idx + 1:]:
            dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            if 0.1 < dist < 3.2:
                atoms.append(('O', (x1 + x2) / 2, (y1 + y2) / 2,
                              (z1 + z2) / 2))
    out.append(('silica', '二氧化硅晶胞（简化）', 'SiO₂',
                'crystals/silica.xyz', 'Si-O 四面体网络', atoms))

    # 干冰：8 个 CO2 分子（简化）
    atoms = []
    a = 5.62
    positions = [(0, 0, 0), (0, 0.5, 0.5), (0.5, 0, 0.5), (0.5, 0.5, 0),
                 (0.25, 0.25, 0.75), (0.25, 0.75, 0.25),
                 (0.75, 0.25, 0.25), (0.75, 0.75, 0.75)]
    for bx, by, bz in positions:
        cx, cy, cz = bx * a, by * a, bz * a
        atoms.append(('C', cx, cy, cz))
        atoms.append(('O', cx - 1.16, cy, cz))
        atoms.append(('O', cx + 1.16, cy, cz))
    out.append(('dry-ice', '干冰分子晶体（示意）', 'CO₂',
                'crystals/dry-ice.xyz', 'CO₂ 分子间范德华力', atoms))

    return out


def main():
    ensure_dir(os.path.join(MOL, 'small'))
    ensure_dir(os.path.join(MOL, 'organic'))
    ensure_dir(os.path.join(MOL, 'proteins'))
    ensure_dir(os.path.join(MOL, 'crystals'))

    catalog = []
    failures = []

    # 分子库：小分子/有机物
    for slug, title, formula, query, textbook, points in LIBRARY:
        category = 'organic' if slug in (
            'ethylene', 'acetylene', 'benzene', 'ethanol',
            'acetic-acid', 'glucose') else 'small'
        try:
            sdf = fetch_cir(query)
            rel = f'{category}/{slug}.sdf'
            write_text(os.path.join(MOL, rel), sdf)
            catalog.append({
                'id': slug, 'title': title, 'formula': formula,
                'category': '有机物' if category == 'organic' else '小分子',
                'file': rel, 'format': 'sdf',
                'textbook': textbook, 'points': points,
                'source': f'{CIR}/{urllib.parse.quote(query)}/sdf?get3d=true',
            })
            print(f'[OK] {title} ({slug})')
        except Exception as exc:
            failures.append((slug, str(exc)))
            print(f'[FAIL] {title} ({slug}): {exc}')
        time.sleep(0.2)

    # 蛋白质
    for slug, title, pdb_id, points in PROTEINS:
        try:
            resp = requests.get(f'{RCSB}/{pdb_id}.pdb',
                                headers=HEADERS, timeout=40)
            resp.raise_for_status()
            rel = f'proteins/{slug}.pdb'
            write_text(os.path.join(MOL, rel), resp.text)
            catalog.append({
                'id': slug, 'title': title, 'formula': '',
                'category': '生物大分子', 'file': rel, 'format': 'pdb',
                'textbook': '选择性必修 · 生物大分子',
                'points': points, 'source': f'{RCSB}/{pdb_id}.pdb',
            })
            print(f'[OK] {title}')
        except Exception as exc:
            failures.append((slug, str(exc)))
            print(f'[FAIL] {title}: {exc}')
        time.sleep(0.2)

    # 晶体
    for slug, title, formula, rel, points, atoms in crystals():
        write_text(os.path.join(MOL, rel),
                   gen_xyz(atoms, f'{title} | ITstudy Chem Lab'))
        catalog.append({
            'id': slug, 'title': title, 'formula': formula,
            'category': '晶体', 'file': rel, 'format': 'xyz',
            'textbook': '选择性必修 · 物质结构与性质',
            'points': points, 'source': '自建晶胞团簇（示意）',
        })
        print(f'[OK] {title}（{len(atoms)} 原子）')

    write_text(os.path.join(MOL, 'catalog.json'),
               json.dumps(catalog, ensure_ascii=False, indent=2))

    print(f'\n分子库 {len(catalog)} 项；失败 {len(failures)} 项')
    if failures:
        print('失败列表：')
        for item in failures:
            print('  ', item)


if __name__ == '__main__':
    main()
