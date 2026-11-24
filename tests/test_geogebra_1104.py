# -*- coding: utf-8 -*-
"""GeoGebra（.ggb）课堂支持回归（2026-11-04）。

覆盖：
- .ggb 归类为 geogebra 条目（默认章节树 + 播放器 URL，课堂内嵌 embed=1）；
- 离线播放器路由：教师/学生可打开，模板使用本地 GeoGebra 包（无公网 CDN）；
- 访问控制：未授权教师/隐藏学生资源/隐藏文件 404，非 .ggb 与目录穿越 404；
- 文件卡片提供「打开（GeoGebra）」入口；
- 离线包资产与许可说明存在。
"""
import json
import pathlib
import re
import shutil
import uuid
from datetime import datetime
from urllib.parse import quote

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, ClassroomSession, Resource, Student,
                        Teacher, TeachingSession)

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
FIXTURE = ROOT / 'tests' / 'fixtures' / 'sample.ggb'
GEOGEBRA_DIR = ROOT / 'static' / 'geogebra'
CSRF = 'geogebra-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def test_offline_bundle_assets_present():
    assert (GEOGEBRA_DIR / 'GeoGebra' / 'deployggb.js').is_file()
    assert (GEOGEBRA_DIR / 'GeoGebra' / 'HTML5' / '5.0' /
            'web3d' / 'web3d.nocache.js').is_file()
    assert (GEOGEBRA_DIR / 'NOTICE.txt').is_file()
    notice = (GEOGEBRA_DIR / 'NOTICE.txt').read_text(encoding='utf-8')
    assert 'GeoGebra' in notice and 'non-commercial' in notice


def test_lesson_kind_and_tree_include_geogebra(app):
    from app.blueprints.resources import _lesson_file_kind
    assert _lesson_file_kind('ggb') == 'geogebra'
    assert _lesson_file_kind('GGB') == 'geogebra'
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__ggb_kind_{sfx}'
    target = UPLOADS / dir_name
    ids = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE, target / 'demo.ggb')
        with app.app_context():
            teacher = Teacher(username=f'__ggb_kt_{sfx}',
                              display_name='GGB教师')
            teacher.set_password('pass123456')
            db.session.add(teacher)
            db.session.flush()
            res = Resource(
                title=f'__ggb_kind_res_{sfx}',
                url=f'/static/uploads/{dir_name}/demo.ggb',
                show_in_student=True, show_in_classroom=True,
                creator_type='teacher', creator_teacher_id=teacher.id,
                creator_name='GGB教师', quiz_mode='none')
            db.session.add(res)
            db.session.commit()
            ids.update(teacher=teacher.id, res=res.id)
        client = _client(app, is_teacher=True, teacher_id=ids['teacher'],
                         teacher_name='GGB教师', teacher_mode='edit')
        page = client.get(f'/study/lesson/{ids["res"]}?mode=classroom')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert '"kind": "geogebra"' in text or '"kind":"geogebra"' in text
        assert 'player_url' in text
        assert f'/study/geogebra/{ids["res"]}' in text
        assert 'embed=1' in text
    finally:
        with app.app_context():
            if ids.get('res'):
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            if ids.get('teacher'):
                Teacher.query.filter_by(id=ids['teacher']).delete(
                    synchronize_session=False)
            db.session.commit()
        shutil.rmtree(target, ignore_errors=True)


def test_player_route_access_and_offline_template(app):
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__ggb_player_{sfx}'
    target = UPLOADS / dir_name
    ids = {}
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE, target / 'demo.ggb')
        shutil.copy(FIXTURE, target / 'demo2.ggb')
        (target / 'notes.txt').write_text('x', encoding='utf-8')
        with app.app_context():
            cls = Class(name=f'__ggb_cls_{sfx}')
            owner = Teacher(username=f'__ggb_own_{sfx}',
                            display_name='课件教师')
            owner.set_password('pass123456')
            other = Teacher(username=f'__ggb_oth_{sfx}',
                            display_name='其他教师')
            other.set_password('pass123456')
            stu = Student(name='GGB学生', student_number=f'__ggb_s_{sfx}',
                          student_class=cls.name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, owner, other, stu])
            db.session.flush()
            stu.class_id = cls.id
            res = Resource(
                title=f'__ggb_player_res_{sfx}',
                url=f'/static/uploads/{dir_name}/demo.ggb',
                show_in_student=True, show_in_classroom=True,
                creator_type='teacher', creator_teacher_id=owner.id,
                creator_name='课件教师', quiz_mode='none')
            db.session.add(res)
            db.session.flush()
            # owner 正在该班上课：学生资源范围跟随授课教师
            db.session.add(TeachingSession(
                resource_id=res.id, teacher_id=owner.id,
                teacher_name=owner.display_name, class_id=cls.id,
                status='active'))
            db.session.add(ClassroomSession(class_id=cls.id,
                                            is_active=True))
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
            ids.update(cls=cls.id, owner=owner.id, other=other.id,
                       stu=stu.id, res=res.id)
        owner_client = _client(app, is_teacher=True,
                               teacher_id=ids['owner'],
                               teacher_name='课件教师',
                               teacher_mode='edit')
        student = _client(app, student_id=ids['stu'],
                          student_name='GGB学生')
        page = owner_client.get(
            f'/study/geogebra/{ids["res"]}?file=demo.ggb')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        # 本地离线包，不依赖公网
        assert '/static/geogebra/GeoGebra/deployggb.js' in text
        assert ("setHTML5Codebase('/static/geogebra/GeoGebra/HTML5/5.0/web3d/', true)"
                in text)
        assert 'www.geogebra.org/apps' not in text
        assert f'/static/uploads/{dir_name}/demo.ggb' in text
        assert 'ai-chat.js' not in text  # 独立页面，无站内 AI/导航
        # 站内 GeoGebra 经 /study/link 打开时需 allow-same-origin（localStorage）
        link = owner_client.get(
            f'/study/link?url=/study/geogebra/{ids["res"]}%3Ffile%3Ddemo.ggb')
        link_text = link.get_data(as_text=True)
        link_sandbox = re.search(
            r'<iframe id="mainFrame"[^>]*sandbox="([^"]+)"', link_text).group(1)
        assert 'allow-same-origin' in link_sandbox
        ext = owner_client.get('/study/link?url=https://example.com/')
        ext_sandbox = re.search(
            r'<iframe id="mainFrame"[^>]*sandbox="([^"]+)"',
            ext.get_data(as_text=True)).group(1)
        assert 'allow-same-origin' not in ext_sandbox
        # 学生可打开
        assert student.get(
            f'/study/geogebra/{ids["res"]}?file=demo.ggb').status_code == 200
        # 非 .ggb / 目录穿越 / 不存在
        for bad in ('notes.txt', '../demo.ggb', 'missing.ggb', '/demo.ggb',
                    './demo.ggb', 'sub/../demo.ggb', 'sub\\demo.ggb',
                    'sub//demo.ggb', 'folder./demo.ggb', 'folder /demo.ggb',
                    'DEMO~1.GGB', 'CON.ggb', 'demo%2e.ggb', 'demo\x00.ggb'):
            assert owner_client.get(
                f'/study/geogebra/{ids["res"]}',
                query_string={'file': bad}).status_code == 404
        # 未授权教师（非创建/共享）不可打开
        other_client = _client(app, is_teacher=True,
                               teacher_id=ids['other'],
                               teacher_name='其他教师', teacher_mode='edit')
        assert other_client.get(
            f'/study/geogebra/{ids["res"]}?file=demo.ggb').status_code == 404
        # 授课教师范围内：资源即使 show_in_student=False 也可打开
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            res.show_in_student = False
            db.session.commit()
        assert student.get(
            f'/study/geogebra/{ids["res"]}?file=demo.ggb').status_code == 200
        # 非主页文件的 show=false 对学生仍隐藏；教师不受限
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            res.show_in_student = True
            res.file_permissions = json.dumps(
                {'demo2.ggb': {'show': False, 'download': True}})
            db.session.commit()
        assert student.get(
            f'/study/geogebra/{ids["res"]}?file=demo2.ggb').status_code == 404
        assert owner_client.get(
            f'/study/geogebra/{ids["res"]}?file=demo2.ggb'
        ).status_code == 200
        # 下课后学生不再跟随该教师：范围外资源 404（严格范围，无全局回退）
        with app.app_context():
            db.session.query(TeachingSession).filter_by(
                class_id=ids['cls']).update(
                    {TeachingSession.end_time: datetime.now(),
                     TeachingSession.status: 'ended'},
                    synchronize_session=False)
            db.session.commit()
        assert student.get(
            f'/study/geogebra/{ids["res"]}?file=demo.ggb').status_code == 404
        # 文件卡片含 GeoGebra 打开入口（卡片展开时按需加载）
        page = owner_client.get('/study')
        assert page.status_code == 200
        files_page = owner_client.get(
            f'/study/resource/{ids["res"]}/files')
        assert files_page.status_code == 200
        assert '打开（GeoGebra）' in files_page.get_data(as_text=True)
        # 编排器文件浏览：.ggb 归类 geogebra（可加入章节树/更换文件）
        api = owner_client.get(
            f'/admin/resources/{ids["res"]}/lesson_files').get_json()
        entries = api.get('entries') or []
        assert any(e.get('name') == 'demo.ggb'
                   and e.get('kind') == 'geogebra' for e in entries)
    finally:
        with app.app_context():
            if ids.get('res'):
                TeachingSession.query.filter_by(
                    resource_id=ids['res']).delete(
                        synchronize_session=False)
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            if ids.get('stu'):
                Student.query.filter_by(id=ids['stu']).delete(
                    synchronize_session=False)
            for key in ('owner', 'other'):
                if ids.get(key):
                    Teacher.query.filter_by(id=ids[key]).delete(
                        synchronize_session=False)
            if ids.get('cls'):
                ClassroomSession.query.filter_by(
                    class_id=ids['cls']).delete(synchronize_session=False)
                Class.query.filter_by(id=ids['cls']).delete(
                    synchronize_session=False)
            db.session.commit()
        shutil.rmtree(target, ignore_errors=True)


def test_courseware_mirror_route_and_three_vendor(app):
    """上传课件镜像路由：注入/同级文件/three 改写/路径与权限校验。"""
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__ggb_bridge_{sfx}'
    target = UPLOADS / dir_name
    ids = {}
    try:
        pkg = target / 'pkg'
        pkg.mkdir(parents=True)
        (pkg / 'index.html').write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body><p id="marker">目录</p></body></html>', encoding='utf-8')
        (pkg / 'plain.html').write_text('ok', encoding='utf-8')
        (pkg / 'notes.txt').write_text('x', encoding='utf-8')
        (pkg / 'app.js').write_text('export const x = 1;', encoding='utf-8')
        (pkg / '学科资源').mkdir()
        (pkg / '学科资源' / 'mod.js').write_text(
            'export const y = 2;', encoding='utf-8')
        (pkg / 'abs.html').write_text(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<script src="/学科资源/mod.js"></script></head>'
            '<body>绝对路径</body></html>', encoding='utf-8')
        (pkg / 'three-lab.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"><script type="importmap">{"imports":{"three":
"https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/"}}
</script></head><body><script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
</script><p>实验室</p></body></html>''', encoding='utf-8')
        (pkg / 'three-nomap.html').write_text('''<!doctype html><html><head>
<meta charset="utf-8"></head><body><script type="module">
import * as THREE from "https://unpkg.com/three@0.186.1/build/three.module.js";
</script><p>无映射</p></body></html>''', encoding='utf-8')
        (pkg / 'legacy.html').write_bytes(
            '<html><head><meta charset="gb2312"></head>'
            '<body>传统编码</body></html>'.encode('gb2312'))
        # 无声明编码且非 UTF-8：无法安全注入，应回退原静态直链
        (pkg / 'binary.html').write_bytes(b'<html>\xff\xfe\x00\x01</html>')
        with app.app_context():
            cls = Class(name=f'__ggb_br_cls_{sfx}')
            owner = Teacher(username=f'__ggb_br_own_{sfx}', display_name='桥接教师')
            owner.set_password('pass123456')
            other = Teacher(username=f'__ggb_br_oth_{sfx}', display_name='其他教师')
            other.set_password('pass123456')
            stu = Student(name='桥接学生', student_number=f'__ggb_br_s_{sfx}',
                          student_class=cls.name, has_changed_password=True)
            stu.set_password('pass123456')
            db.session.add_all([cls, owner, other, stu])
            db.session.flush()
            stu.class_id = cls.id
            res = Resource(
                title=f'__ggb_br_res_{sfx}',
                url=f'/static/uploads/{dir_name}/pkg/index.html',
                show_in_student=True, show_in_classroom=True,
                creator_type='teacher', creator_teacher_id=owner.id,
                creator_name='桥接教师', quiz_mode='none')
            db.session.add(res)
            db.session.flush()
            db.session.add(TeachingSession(resource_id=res.id, teacher_id=owner.id,
                                           teacher_name=owner.display_name,
                                           class_id=cls.id, status='active'))
            db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
            db.session.commit()
            from app.blueprints.auth import invalidate_active_class_cache
            invalidate_active_class_cache()
            ids.update(cls=cls.id, owner=owner.id, other=other.id,
                       stu=stu.id, res=res.id)
        student = _client(app, student_id=ids['stu'], student_name='桥接学生')

        def _url(path, token='', origin=''):
            from urllib.parse import urlencode
            qs = {}
            if token:
                qs['token'] = token
            if origin:
                qs['origin'] = origin
            url = f'/study/courseware/{ids["res"]}/{path}'
            if qs:
                url += '?' + urlencode(qs)
            return url

        ok = student.get(_url('pkg/index.html', 't-123', 'http://localhost'))
        assert ok.status_code == 200
        text = ok.get_data(as_text=True)
        assert f'<base href="/study/courseware/{ids["res"]}/pkg/index.html">' in text
        assert 'ggb-courseware-bootstrap.js' in text
        assert 'data-token="t-123"' in text
        assert 'data-host-origin="http://localhost"' in text
        assert '目录' in text
        assert 'no-store' in ok.headers['Cache-Control']
        # 根绝对路径（站点根=课件目录的构建产物）回写为资源目录内真实文件
        abs_page = student.get(_url('pkg/abs.html')).get_data(as_text=True)
        assert (f'/study/courseware/{ids["res"]}/pkg/'
                + quote('学科资源', safe='') + '/mod.js') in abs_page
        assert '绝对路径' in abs_page
        # 同级非 HTML 文件原样提供（正确 MIME + CORS）
        sibling = student.get(_url('pkg/app.js'))
        assert sibling.status_code == 200
        assert 'javascript' in sibling.headers['Content-Type']
        assert sibling.headers['Access-Control-Allow-Origin'] == '*'
        assert student.get(_url('pkg/notes.txt')).status_code == 200
        # 点段 / 反斜杠 / Windows 别名 / NUL / 越界文件
        for bad in ('pkg/../index.html', 'pkg//index.html', 'pkg\\index.html',
                    'PKG~1.INDEX.HTML', 'pkg/index.html\x00', 'missing.html'):
            assert student.get(f'/study/courseware/{ids["res"]}/{bad}').status_code == 404
        # 未授权教师 404；创建者教师可打开
        other_client = _client(app, is_teacher=True, teacher_id=ids['other'],
                               teacher_name='其他教师', teacher_mode='edit')
        assert other_client.get(f'/study/courseware/{ids["res"]}/pkg/index.html').status_code == 404
        owner_client = _client(app, is_teacher=True, teacher_id=ids['owner'],
                               teacher_name='桥接教师', teacher_mode='edit')
        assert owner_client.get(f'/study/courseware/{ids["res"]}/pkg/index.html').status_code == 200
        # 文件级「展示」隐藏：学生 404；编排显式对学生可见后放行
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            res.file_permissions = json.dumps({'pkg/plain.html': {'show': False}})
            db.session.commit()
        assert student.get(_url('pkg/plain.html')).status_code == 404
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            res.lesson_tree = json.dumps([{'id': 'sec', 'title': '章节', 'items': [
                {'id': 'p', 'title': 'plain', 'kind': 'link',
                 'src': 'pkg/plain.html',
                 'visible': {'teacher': True, 'student': True}}]}],
                ensure_ascii=False)
            db.session.commit()
        assert student.get(_url('pkg/plain.html')).status_code == 200
        # three CDN 引用改写：页面自带 importmap 时改写其 URL 且不重复注入
        three_page = student.get(_url('pkg/three-lab.html')).get_data(as_text=True)
        assert 'cdn.jsdelivr.net' not in three_page
        assert '/study/three/0.186.1/build/three.module.js' in three_page
        assert '/study/three/0.186.1/examples/jsm/' in three_page
        assert three_page.count('<script type="importmap">') == 1
        assert '实验室' in three_page
        # 无 importmap 的页面补一份本地映射
        nomap = student.get(_url('pkg/three-nomap.html')).get_data(as_text=True)
        assert 'unpkg.com' not in nomap
        assert nomap.count('<script type="importmap">') == 1
        assert '"three":"/study/three/0.186.1/build/three.module.js"' in nomap
        # 传统编码页面按声明编码转码后注入，内容不破坏
        legacy = student.get(_url('pkg/legacy.html'))
        assert legacy.status_code == 200
        legacy_text = legacy.get_data(as_text=True)
        assert '传统编码' in legacy_text
        assert 'ggb-courseware-bootstrap.js' in legacy_text
        # 无法解码时原样留在镜像权限域，不退回无授权的静态地址。
        binary = student.get(f'/study/courseware/{ids["res"]}/pkg/binary.html',
                             follow_redirects=False)
        assert binary.status_code == 200
        assert binary.get_data() == b'<html>\xff\xfe\x00\x01</html>'
        assert 'Location' not in binary.headers

        # three 本地模块：正确 MIME/CORS/immutable，版本白名单与路径包含
        module = student.get('/study/three/0.186.1/build/three.module.js')
        assert module.status_code == 200
        assert 'javascript' in module.headers['Content-Type']
        assert module.headers['Access-Control-Allow-Origin'] == '*'
        assert 'immutable' in module.headers['Cache-Control']
        controls = student.get(
            '/study/three/0.186.1/examples/jsm/controls/OrbitControls.js')
        assert controls.status_code == 200
        assert student.get('/study/three/9.9.9/build/three.module.js').status_code == 404
        assert student.get('/study/three/0.186.1/../LICENSE').status_code == 404
        assert student.get('/study/three/0.186.1/missing.js').status_code == 404
    finally:
        with app.app_context():
            if ids.get('res'):
                TeachingSession.query.filter_by(resource_id=ids['res']).delete(
                    synchronize_session=False)
                Resource.query.filter_by(id=ids['res']).delete(synchronize_session=False)
            if ids.get('stu'):
                Student.query.filter_by(id=ids['stu']).delete(synchronize_session=False)
            for key in ('owner', 'other'):
                if ids.get(key):
                    Teacher.query.filter_by(id=ids[key]).delete(synchronize_session=False)
            if ids.get('cls'):
                ClassroomSession.query.filter_by(class_id=ids['cls']).delete(
                    synchronize_session=False)
                Class.query.filter_by(id=ids['cls']).delete(synchronize_session=False)
            db.session.commit()
        shutil.rmtree(target, ignore_errors=True)
