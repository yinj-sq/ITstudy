# -*- coding: utf-8 -*-
"""化学仿真 V6.1.0：离线 Ketcher 工作台、本地分子库/可视化与种子回归。"""
import json
import os

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import Resource, Subject
from app.blueprints.chem_lab import ensure_chem_lab_resource

CSRF = 'chem-lab-csrf'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHEM_DIR = os.path.join(ROOT, 'static', 'chem-lab')


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_chem_lab_deep_links(app):
    client = _client(app, is_admin=True, admin_name='管理员')
    page = client.get('/chem-lab?mol=water')
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and 'chemInitial' in text
    assert '"id": "water"' in text
    page = client.get('/chem-lab?visual=nacl')
    text = page.get_data(as_text=True)
    assert '"visual": "nacl"' in text
    assert 'chemVisualCopy' in text
    page = client.get('/chem-lab?smiles=CCO')
    text = page.get_data(as_text=True)
    assert '"smiles": "CCO"' in text


def test_page_requires_login(app):
    anon = app.test_client()
    resp = anon.get('/chem-lab')
    assert resp.status_code in (302, 303)
    assert anon.get('/chem-lab/sketch').status_code in (302, 303)


def test_page_renders_for_admin_and_student(app):
    admin = _client(app, is_admin=True, admin_name='管理员')
    resp = admin.get('/chem-lab')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    for marker in ('化学仿真', '绘制 + 3D', '/chem-lab/sketch',
                   'chem-ketcher-frame', 'chem3dmol', '3Dmol-min.js',
                   '可视化化学', '内置分子库', 'chem_lab.js'):
        assert marker in text
    assert 'moldraw.com' not in text
    csp = resp.headers.get('Content-Security-Policy', '')
    assert "frame-src 'self'" in csp and 'moldraw' not in csp
    assert "'unsafe-eval' " not in csp
    from app.models import Student
    with app.app_context():
        stu = Student.query.filter_by(student_number='__chem_stu').first()
        if stu is None:
            stu = Student(name='化仿学生', student_number='__chem_stu',
                          has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add(stu)
            db.session.commit()
        stu_id = stu.id
    student = _client(app, student_id=stu_id, student_name='化仿学生')
    assert student.get('/chem-lab').status_code == 200


def test_ketcher_frame_and_artifacts(app):
    client = _client(app, is_admin=True, admin_name='管理员')
    resp = client.get('/chem-lab/sketch')
    assert resp.status_code == 200
    assert 'no-store' in resp.headers.get('Cache-Control', '')
    text = resp.get_data(as_text=True)
    assert 'ketcher/assets/' in text and 'type="module"' in text
    csp = resp.headers.get('Content-Security-Policy', '')
    assert "'unsafe-eval' 'wasm-unsafe-eval'" in csp
    assert "''" not in csp
    assert 'worker-src' in csp and 'blob:' in csp
    assert '/static/chem-lab/' in csp
    ketcher_dir = os.path.join(CHEM_DIR, 'ketcher')
    assert os.path.isfile(os.path.join(ketcher_dir, 'index.html'))
    assets = os.listdir(os.path.join(ketcher_dir, 'assets'))
    assert any(name.startswith('index-') and name.endswith('.js')
               for name in assets)
    assert any('conformer.worker' in name and name.endswith('.js')
               for name in assets)
    mol3d = os.path.join(CHEM_DIR, 'vendor', '3dmol')
    assert os.path.isfile(os.path.join(mol3d, '3Dmol-min.js'))
    assert os.path.isfile(os.path.join(mol3d, 'LICENSE'))


def test_viewer_frame_and_visual_frame(app):
    client = _client(app, is_admin=True, admin_name='管理员')
    resp = client.get('/chem-lab/frame')
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'molstar.js' in text and 'viewer-app.js' in text
    # CSP 收窄到本目录
    csp = resp.headers.get('Content-Security-Policy', '')
    assert '/static/chem-lab/' in csp
    # 可视化帧：黑名单外的 slug 404
    assert client.get('/chem-lab/visual/not-exist/frame').status_code == 404
    # 合法 slug：帧路由重定向到镜像静态路径（保证内页相对资源正确）
    visual = client.get('/chem-lab/visual/nacl/frame')
    assert visual.status_code in (301, 302, 303, 307, 308)
    assert '/chem-lab/visual-chem/nacl.html' in visual.headers['Location']
    visual = client.get(visual.headers['Location'])
    assert visual.status_code == 200
    visual_text = visual.get_data(as_text=True)
    assert 'chem-lab-embed-style' in visual_text
    assert 'back-button.js' not in visual_text
    assert 'api.php' not in visual_text
    # _vip 内嵌页依赖必须为应用根绝对路径：运行时目录/缓存差异曾导致
    # ZnS/CaF2 的 three.js、OrbitControls、Engine.js 404（3D 引擎无法启动）。
    vip_dir = os.path.join(CHEM_DIR, 'visual-chem', '_vip')
    for name in ('zns.html', 'caf2.html'):
        vip = open(os.path.join(vip_dir, name), encoding='utf-8').read()
        assert '/chem-lab/visual-chem/vendor/three170-bundle.js' in vip
        assert 'src="vendor/three170-bundle.js"' not in vip
        assert 'src="ui-glass.js"' not in vip
    shell = open(os.path.join(CHEM_DIR, 'visual-chem',
                              'jingbao-yuandian.html'), encoding='utf-8').read()
    assert "'/chem-lab/visual-chem/' + file" in shell


def test_seed_resource_and_catalog(app):
    with app.app_context():
        row = Resource.query.filter_by(builtin_key='chem_lab').first()
        assert row is not None and row.is_builtin
        assert row.url == '/chem-lab'
        assert row.show_in_student and row.show_in_classroom
        subject = db.session.get(Subject, row.subject_id)
        assert subject is not None and subject.name == '仿真实验'
        tree = json.loads(row.lesson_tree)
        assert tree[0]['items'][0]['src'] == '/chem-lab'
    with open(os.path.join(CHEM_DIR, 'molecules', 'catalog.json'),
              encoding='utf-8') as f:
        catalog = json.load(f)
    assert len(catalog) >= 27
    assert sum(1 for c in catalog if c['category'] == '晶体') == 7


def test_seed_keeps_renamed_builtin_subject(app):
    """内置学科原地改名后，重启种子不再按旧名称新建重复学科。"""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        row = Resource.query.filter_by(builtin_key='chem_lab').first()
        subject = db.session.get(Subject, row.subject_id)
        original_name = subject.name
        renamed = f'__chem_renamed_{suffix}'
        subject.name = renamed
        db.session.commit()
        before = Subject.query.filter_by(name='仿真实验').count()
    cache.clear()
    try:
        with app.app_context():
            ensure_chem_lab_resource()
        with app.app_context():
            row = Resource.query.filter_by(builtin_key='chem_lab').first()
            subject = db.session.get(Subject, row.subject_id)
            assert subject is not None and subject.name == renamed
            assert Subject.query.filter_by(
                name='仿真实验').count() == before
    finally:
        with app.app_context():
            subject = db.session.get(Subject, row.subject_id)
            if subject is not None:
                subject.name = original_name
                db.session.commit()
            cache.clear()


def test_copper_lab_removed(app):
    client = _client(app, is_admin=True, admin_name='管理员')
    assert client.get('/copper-lab').status_code == 404
    assert not os.path.isdir(os.path.join(ROOT, 'static', 'copper-lab'))
    # 123/ 为可选外置课件目录，不随安装包/仓库运行；存在时才校验导航页
    copper_dir = os.path.join(ROOT, '123', '铜匠实验室')
    if os.path.isdir(copper_dir):
        assert os.path.isfile(os.path.join(copper_dir, 'index.html'))
    with app.app_context():
        assert Resource.query.filter(Resource.builtin_key.like(
            'copper_lab%')).count() == 0


def test_diatomic_gases_have_correct_atoms_and_bonds():
    expected = {
        'hydrogen': ('H', 1, 0.74),
        'oxygen': ('O', 2, 1.21),
        'nitrogen': ('N', 3, 1.10),
        'chlorine': ('Cl', 1, 1.99),
    }
    for name, (symbol, order, length) in expected.items():
        with open(os.path.join(CHEM_DIR, 'molecules', 'small', name + '.sdf'),
                  encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        assert int(lines[3][:3]) == 2
        assert int(lines[3][3:6]) == 1
        assert all(line[31:34].strip() == symbol for line in lines[4:6])
        assert int(lines[6][6:9]) == order
        distance = abs(float(lines[4][:10]) - float(lines[5][:10]))
        assert distance == pytest.approx(length)


def test_cir_diatomic_queries_are_unambiguous():
    from tools.fetch_chem_molecules import LIBRARY
    queries = {row[0]: row[3] for row in LIBRARY}
    assert queries['hydrogen'] == '[H][H]'
    assert queries['oxygen'] == 'O=O'
    assert queries['nitrogen'] == 'N#N'
    assert queries['chlorine'] == 'ClCl'

