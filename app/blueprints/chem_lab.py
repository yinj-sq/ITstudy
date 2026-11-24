# -*- coding: utf-8 -*-
"""化学仿真工作台（V6.1.0）。

- /chem-lab                       工作台：离线 Ketcher 2D 绘制 + 3Dmol.js 实时 3D
                                  + 本地可视化化学/分子库
- /chem-lab/sketch                离线 Ketcher 编辑器帧（同源 iframe）
- /chem-lab/frame                 本地 Molstar 查看器帧（分子库）
- /chem-lab/visual/<slug>/frame   可视化化学页面帧（slug 白名单）
- /chem-lab/visual-chem/<path>    可视化化学资源镜像（按原目录结构，保证相对路径）

静态资源位于 static/chem-lab/；Ketcher 构建产物位于 static/chem-lab/ketcher/。
"""
import json
import os
import uuid

from flask import (Blueprint, Response, abort, redirect, render_template,
                   request, send_from_directory, session, url_for)

from app.decorators import authenticated_required

chem_lab_bp = Blueprint('chem_lab', __name__, url_prefix='')

CHEM_LAB_URL = '/chem-lab'
CHEM_LAB_KEY = 'chem_lab'
CHEM_LAB_TITLE = '化学仿真'
CHEM_LAB_SUBJECT = '仿真实验'

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_CHEM_DIR = os.path.join(_BASE, 'static', 'chem-lab')
_MOL_DIR = os.path.join(_CHEM_DIR, 'molecules')
_VISUAL_DIR = os.path.join(_CHEM_DIR, 'visual-chem')

# 可视化化学：21 个模型入口（slug -> 文件/标题/分组/说明）
VISUAL_GROUPS = [
    ('crystal', '晶体空间实验室', 'fa-cubes'),
    ('periodic', '元素周期律', 'fa-table-cells'),
    ('molecule', '分子结构', 'fa-atom'),
    ('electrochem', '电化学', 'fa-bolt'),
    ('organic', '立体有机', 'fa-shapes'),
]
VISUAL_PAGES = {
    'crystal-origin': {
        'file': 'jingbao-yuandian.html', 'title': '晶胞原点转换',
        'group': 'crystal', 'desc': 'CsCl / NaCl / ZnS / CaF₂ 四种晶胞切换'},
    'nacl': {'file': 'nacl.html', 'title': '氯化钠 NaCl',
             'group': 'crystal', 'desc': '面心立方晶胞与配位环境'},
    'cscl': {'file': 'cscl.html', 'title': '氯化铯 CsCl',
             'group': 'crystal', 'desc': '体心立方晶胞与 8 配位'},
    'sic': {'file': 'sic.html', 'title': '碳化硅 SiC',
            'group': 'crystal', 'desc': '金刚石型结构'},
    'fe': {'file': 'fe.html', 'title': '金属铁 Fe',
           'group': 'crystal', 'desc': '金属晶体堆积'},
    'po': {'file': 'po.html', 'title': '金属钋 Po',
           'group': 'crystal', 'desc': '简单立方堆积'},
    'periodic': {'file': '元素周期表.html', 'title': '118 元素周期表',
                 'group': 'periodic', 'desc': '电子层模式与周期律趋势'},
    'c60': {'file': 'c60.html', 'title': 'C₆₀ 足球烯',
            'group': 'molecule', 'desc': '富勒烯的球形笼状结构'},
    'co2-pi': {'file': 'dapijian-co2.html', 'title': 'CO₂ 大 π 键',
               'group': 'molecule', 'desc': 'Π₃⁴ × 2 离域 π 键'},
    'ozone-pi': {'file': 'dapijian-ozone.html', 'title': 'O₃ 大 π 键',
                 'group': 'molecule', 'desc': 'Π₃⁴ 离域 π 键'},
    'so3-pi': {'file': 'dapijian-so3.html', 'title': 'SO₃ 大 π 键',
               'group': 'molecule', 'desc': 'Π₄⁶ 离域 π 键'},
    'benzene-pi': {'file': 'dapijian-ben.html', 'title': '苯 大 π 键',
                   'group': 'molecule', 'desc': 'Π₆⁶ 离域 π 键'},
    'pyrrole-pi': {'file': 'dapijian-pyrrole.html', 'title': '吡咯 大 π 键',
                   'group': 'molecule', 'desc': 'Π₅⁶ 离域 π 键'},
    'pyridine-pi': {'file': 'dapijian-pyridine.html', 'title': '吡啶 大 π 键',
                    'group': 'molecule', 'desc': 'Π₆⁶ 离域 π 键'},
    'battery': {'file': 'dianchi.html', 'title': '原电池原理',
                'group': 'electrochem', 'desc': '四套原电池装置'},
    'electrolysis': {'file': 'dianjiao.html', 'title': '电解池原理',
                     'group': 'electrochem', 'desc': '铜锌电解池'},
    'bromoethane': {'file': 'xiuyiwan.html', 'title': '溴乙烷',
                    'group': 'organic', 'desc': '立体结构与反应机理'},
    'ethylene': {'file': 'yixi.html', 'title': '乙烯',
                 'group': 'organic', 'desc': '平面结构与加成反应'},
    'acetylene': {'file': 'yique.html', 'title': '乙炔',
                  'group': 'organic', 'desc': '直线型结构与反应'},
    'benzene': {'file': 'ben.html', 'title': '苯的反应机理',
                'group': 'organic', 'desc': '取代反应与空间结构'},
    'collinear': {'file': 'gongxiangongmian.html', 'title': '有机分子共线共面',
                  'group': 'organic', 'desc': '共线共面专题'},
}


# ── 内置资源种子 ──────────────────────────────────────────────

def _suppressed(key):
    from app.models import SystemConfig
    return SystemConfig.get(f'builtin_suppressed:{key}') == '1'


def _default_lesson_tree():
    return [{
        'id': uuid.uuid4().hex[:12], 'title': '化学仿真', 'type': 'section',
        'children': [], 'items': [{
            'id': uuid.uuid4().hex[:12], 'title': '化学仿真工作台',
            'kind': 'link', 'src': CHEM_LAB_URL,
            'visible': {'teacher': True, 'student': True},
        }],
    }]


def ensure_chem_lab_resource():
    """幂等创建/修复化学仿真的内置资源行。"""
    from app.extensions import db
    from app.models import Resource, Subject, resource_audience
    from app.utils import invalidate_lookup_cache

    if _suppressed(CHEM_LAB_KEY):
        return 0
    row = Resource.query.filter_by(builtin_key=CHEM_LAB_KEY).order_by(
        Resource.id).first()
    subject = None
    if row is not None and row.subject_id:
        # 管理员可能已原地重命名内置资源所属学科；优先沿用资源现有学科，
        # 否则每次启动都会按旧名称再建一个“仿真实验”学科。
        subject = db.session.get(Subject, row.subject_id)
    if subject is None:
        subject = Subject.query.filter_by(name=CHEM_LAB_SUBJECT).first()
    subject_created = subject is None
    if subject_created:
        max_order = db.session.query(db.func.max(Subject.sort_order)).scalar() or 0
        subject = Subject(name=CHEM_LAB_SUBJECT, sort_order=max_order + 1)
        db.session.add(subject)
        db.session.flush()
    changed = int(subject_created)
    if row is None:
        row = Resource(
            title=CHEM_LAB_TITLE, url=CHEM_LAB_URL, subject_id=subject.id,
            creator_type='admin', creator_name='系统内置',
            is_builtin=True, builtin_key=CHEM_LAB_KEY, is_public=False,
            show_in_student=True, show_in_classroom=True, quiz_mode='none',
            lesson_tree=json.dumps(_default_lesson_tree(),
                                   ensure_ascii=False))
        db.session.add(row)
        db.session.flush()
        changed += 1
    else:
        if not row.is_builtin:
            row.is_builtin = True
            changed += 1
        if row.is_public:
            row.is_public = False
            changed += 1
        if row.subject_id is None:
            row.subject_id = subject.id
            changed += 1
        if not row.lesson_tree:
            row.lesson_tree = json.dumps(_default_lesson_tree(),
                                         ensure_ascii=False)
            changed += 1
    if not db.session.execute(resource_audience.select().where(
            resource_audience.c.resource_id == row.id)).first():
        db.session.execute(resource_audience.insert().values(
            resource_id=row.id, grade=None, subject_id=None))
        changed += 1
    db.session.commit()
    if subject_created:
        invalidate_lookup_cache('subjects')
    if changed:
        from app.blueprints.resources import _invalidate_study_caches
        _invalidate_study_caches()
    return changed


# ── 目录与状态 ────────────────────────────────────────────────

def _load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_molecule_catalog():
    data = _load_json(os.path.join(_MOL_DIR, 'catalog.json'), [])
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _visual_groups():
    groups = []
    for key, name, icon in VISUAL_GROUPS:
        items = [{'slug': slug, **page}
                 for slug, page in VISUAL_PAGES.items()
                 if page.get('group') == key]
        if items:
            groups.append({'key': key, 'name': name, 'icon': icon,
                           'items': items})
    return groups


def _chem_uid():
    if session.get('student_id'):
        return f'student_{session["student_id"]}'
    if session.get('teacher_id'):
        return f'teacher_{session["teacher_id"]}'
    if session.get('admin_account_id'):
        return f'admin_{session["admin_account_id"]}'
    return 'admin'


# ── 路由：工作台与帧 ──────────────────────────────────────────

@chem_lab_bp.route('/chem-lab', strict_slashes=False)
@authenticated_required
def chem_lab_index():
    catalog = load_molecule_catalog()
    mol_id = (request.args.get('mol') or '').strip()
    initial_molecule = None
    if mol_id:
        initial_molecule = next(
            (item for item in catalog
             if item.get('id') == mol_id or item.get('title') == mol_id),
            None)
    visual = (request.args.get('visual') or '').strip()
    if visual not in VISUAL_PAGES:
        visual = ''
    smiles = (request.args.get('smiles') or '').strip()[:2048]
    return render_template(
        'chem_lab.html',
        catalog=catalog,
        visual_groups=_visual_groups(),
        initial_molecule=initial_molecule,
        initial_visual=visual,
        initial_smiles=smiles,
        chem_uid=_chem_uid(),
        embed=request.args.get('embed') == '1',
    )


@chem_lab_bp.route('/chem-lab/sketch')
@authenticated_required
def sketch_frame():
    """离线 Ketcher 编辑器入口；构建产物与 Flask 同源，便于 iframe 通信。"""
    path = os.path.join(_CHEM_DIR, 'ketcher', 'index.html')
    try:
        with open(path, encoding='utf-8') as f:
            html = f.read()
    except OSError:
        abort(404)
    resp = Response(html, mimetype='text/html')
    # 构建产物文件名带 hash；禁止缓存 HTML，避免升级后旧 HTML 指向已删除资源
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@chem_lab_bp.route('/chem-lab/frame')
@authenticated_required
def chem_lab_frame():
    path = os.path.join(_CHEM_DIR, 'viewer.html')
    try:
        with open(path, encoding='utf-8') as f:
            html = f.read()
    except OSError:
        abort(404)
    return Response(html, mimetype='text/html')


@chem_lab_bp.route('/chem-lab/visual/<slug>/frame')
@authenticated_required
def visual_frame(slug):
    page = VISUAL_PAGES.get(slug)
    if not page:
        abort(404)
    # 重定向到镜像静态路径：页面内的相对资源（ui-glass.css、vendor/three.js、
    # _vip/*.html）必须与 HTML 同目录解析；在帧路由 URL 下会落到错误目录，
    # 晶胞页的 ZnS/CaF₂ 曾因此 404。旧书签/旧 JS 也可通过本路由兼容。
    return redirect(url_for('chem_lab.visual_asset', filename=page['file']))


@chem_lab_bp.route('/chem-lab/visual-chem/<path:filename>')
@authenticated_required
def visual_asset(filename):
    """按 visual-chem 原目录结构直出资源。

    页面内大量相对路径（ui-glass.css、vendor/three.js、_vip/*.html）只有在
    与文件同层的 URL 下才能正确解析；帧路由的 /chem-lab/visual/<slug>/frame
    会让相对路径落到错误的目录（晶胞页曾因此 404/重影）。
    """
    return send_from_directory(_VISUAL_DIR, filename)
