# -*- coding: utf-8 -*-
"""上传课件 HTML 路径适配回归（V6.1.0 · 2026-11-19）。

背景：课件按“站点根 = 课件目录”构建（Vite base='/学科资源/平台资源/xxSPA/'），
上传到 /static/uploads/<资源目录>/ 后根绝对引用 404 并被 404 处理重定向到
/study（text/html），模块脚本/样式因 MIME 不符整体失效。

覆盖：
- 静态直服（目录页内相对链接打开）也走响应期适配；
- 只改写映射后确实存在于本资源目录的文件，未知绝对路径原样保留；
- 查询串/片段保留；three CDN 改写与 importmap 补全；
- 镜像路由与静态直服共用同一适配实现。
"""
import shutil
import pathlib
import uuid
import json
import re
import time
from urllib.parse import quote, urlencode

import pytest

from app import create_app
from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
from app.extensions import db
from app.models import Class, Resource, Student, SystemConfig, Teacher
from app.utils import adapt_courseware_html, adapt_courseware_script, password_fingerprint


@pytest.fixture(scope='module')
def app():
    return create_app()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_adapt_courseware_html_unit(tmp_path):
    dir_root = tmp_path / 'resource'
    spa = dir_root / 'pkg' / '学科资源' / '平台资源' / '知了实验室SPA'
    _write(spa / 'assets' / 'index-abc.js', 'export const x = 1;')
    _write(spa / 'assets' / 'index.css', 'body{}')
    doc_rel = 'pkg/学科资源/平台资源/知了实验室SPA/index-offline.html'
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<script src="/学科资源/平台资源/知了实验室SPA/assets/index-abc.js?v=1"></script>'
        '<link rel="stylesheet" href="/学科资源/平台资源/知了实验室SPA/assets/index.css">'
        '<script src="/不存在/keep.js"></script>'
        '<style>.bg{background:url(/学科资源/平台资源/知了实验室SPA/assets/index.css)}</style>'
        '</head><body>知了</body></html>')
    adapted, count = adapt_courseware_html(
        html, str(dir_root), doc_rel, '资源目录')
    prefix = '/static/uploads/' + quote('资源目录', safe='')
    assert count == 3
    assert (prefix + '/' + quote(
        'pkg/学科资源/平台资源/知了实验室SPA/assets/index-abc.js',
        safe='/') + '?v=1') in adapted
    assert (prefix + '/' + quote(
        'pkg/学科资源/平台资源/知了实验室SPA/assets/index.css',
        safe='/')) in adapted
    assert '/不存在/keep.js' in adapted
    assert 'url(' + prefix + '/' + quote(
        'pkg/学科资源/平台资源/知了实验室SPA/assets/index.css',
        safe='/') + ')' in adapted
    # 页面本身无需适配时返回原文
    plain = '<!doctype html><html><body><a href="demo.html">ok</a></body></html>'
    same, n = adapt_courseware_html(
        plain, str(dir_root), 'pkg/index.html', '资源目录')
    assert n == 0 and same == plain


def test_adapt_courseware_html_three_cdn(tmp_path):
    dir_root = tmp_path / 'resource'
    dir_root.mkdir(parents=True)
    html = ('<!doctype html><html><head><meta charset="utf-8">'
            '<script type="importmap">{"imports":{"three":'
            '"https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.js",'
            '"three/addons":"https://cdn.jsdelivr.net/npm/three@0.186.1/'
            'examples/jsm/"}}</script></head><body></body></html>')
    adapted, count = adapt_courseware_html(
        html, str(dir_root), 'index.html', '资源目录')
    assert count == 2
    assert 'cdn.jsdelivr.net' not in adapted
    assert '/study/three/0.186.1/build/three.module.js' in adapted
    assert '/study/three/0.186.1/examples/jsm/' in adapted
    assert adapted.count('<script type="importmap">') == 1


def test_static_courseware_html_adaptation(app):
    sfx = uuid.uuid4().hex[:8]
    dir_name = f'__cw_adapt_{sfx}'
    uploads_root = pathlib.Path(app.static_folder) / 'uploads'
    target = (uploads_root / dir_name / 'pkg' / '学科资源' / '平台资源'
              / '知了实验室SPA')
    try:
        _write(target / 'assets' / 'index-abc.js', 'export const x = 1;')
        _write(target / 'assets' / 'index.css', 'body{}')
        _write(target / 'index-offline.html', (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<script src="/学科资源/平台资源/知了实验室SPA/assets/index-abc.js"></script>'
            '<link rel="stylesheet" href="/学科资源/平台资源/知了实验室SPA/assets/index.css">'
            '<script src="/不存在/keep.js"></script>'
            '</head><body>知了实验室</body></html>'))
        _write(uploads_root / dir_name / 'pkg' / 'plain.html',
               '<!doctype html><html><body>原样</body></html>')

        client = app.test_client()
        page_path = ('/static/uploads/{}/pkg/学科资源/平台资源/知了实验室SPA/'
                     'index-offline.html').format(dir_name)
        resp = client.get(quote(page_path, safe='/'))
        assert resp.status_code == 200
        assert 'text/html' in resp.headers['Content-Type']
        text = resp.get_data(as_text=True)
        prefix = '/static/uploads/' + quote(dir_name, safe='') + '/'
        assert prefix + quote(
            'pkg/学科资源/平台资源/知了实验室SPA/assets/index-abc.js',
            safe='/') in text
        assert prefix + quote(
            'pkg/学科资源/平台资源/知了实验室SPA/assets/index.css',
            safe='/') in text
        assert '/不存在/keep.js' in text
        assert '知了实验室' in text
        assert 'no-cache' in resp.headers.get('Cache-Control', '')

        plain = client.get(
            '/static/uploads/{}/pkg/plain.html'.format(dir_name))
        assert plain.status_code == 200
        assert plain.get_data(as_text=True) == (
            '<!doctype html><html><body>原样</body></html>')
    finally:
        shutil.rmtree(uploads_root / dir_name, ignore_errors=True)


def test_vite_preload_base_and_inline_urls(tmp_path):
    root = tmp_path / 'resource'
    package = root / '3D' / '学科资源' / '知了SPA'
    _write(package / 'assets' / 'index.js', '')
    _write(package / 'assets' / 'lab.js', 'export const x=1;')
    _write(package / 'assets' / 'lab.css', 'body{}')
    target = '/study/courseware-view/grant/38/'
    script = ('const __vite__mapDeps=(i)=>["assets/lab.js","assets/lab.css"];'
              'const q="modulepreload",By=function(S){return"/"+S};'
              'const path="/assets/lab.js";const route="/experiment/chem-tyndall";'
              'const api="/api/experiments";import("./lab.js");')
    changed = adapt_courseware_script(
        script, str(root), '3D/学科资源/知了SPA/assets/index.js', 'resource', target)
    base = target + quote('3D/学科资源/知了SPA/', safe='/')
    assert 'By=function(S){return' + repr(base) + '+S}' in changed
    assert base + 'assets/lab.js' in changed
    assert '"/experiment/chem-tyndall"' in changed
    assert '"/api/experiments"' in changed
    assert 'import("./lab.js")' in changed
    html = ('<head><script>const file="/assets/lab.js";</script>'
            '<script type="module" src="/assets/index.js"></script></head>')
    changed, _ = adapt_courseware_html(
        html, str(root), '3D/学科资源/知了SPA/index.html', 'resource', target_root=target)
    assert base + 'assets/index.js' in changed and base + 'assets/lab.js' in changed


@pytest.fixture
def courseware_package(app):
    suffix = uuid.uuid4().hex[:8]
    dir_name = '__courseware_access_' + suffix
    uploads = pathlib.Path(app.static_folder) / 'uploads'
    root = uploads / dir_name
    _write(root / 'pkg' / 'index.html',
           '<html><head><meta charset="utf-8"><script type="module" src="app.js"></script>'
           '</head><body><a href="sub.html">目录内导航</a></body></html>')
    _write(root / 'pkg' / 'app.js', 'export const x=1;')
    _write(root / 'pkg' / 'sub.html', '<html><body>子课件</body></html>')
    _write(root / 'pkg' / 'data.json', '{"map":"history"}')
    _write(root / 'pkg' / 'hidden.html', '<html>隐藏</html>')
    saved = {}
    with app.app_context():
        for key in ('courseware_public_enabled', 'student_access_enabled'):
            record = db.session.get(SystemConfig, key)
            saved[key] = record.value if record else None
        SystemConfig.set('courseware_public_enabled', 'false')
        SystemConfig.set('student_access_enabled', 'true')
        teacher = Teacher(username='__cw_teacher_' + suffix, display_name='课件教师')
        teacher.set_password('CoursewarePass1')
        cls = Class(name='__cw_class_' + suffix)
        student = Student(name='课件学生', student_number='__cw_student_' + suffix,
                          student_class=cls.name, has_changed_password=True)
        student.set_password('CoursewarePass1')
        db.session.add_all([teacher, cls, student])
        db.session.flush()
        student.class_id = cls.id
        resource = Resource(title=dir_name, url=f'/static/uploads/{dir_name}/pkg/index.html',
                            creator_type='teacher', creator_teacher_id=teacher.id,
                            is_public=True, show_in_student=True, show_in_classroom=True,
                            file_permissions=json.dumps({'pkg/hidden.html': {'show': False}}))
        other = Resource(title=dir_name + '-other', url=f'/static/uploads/{dir_name}/pkg/sub.html',
                         creator_type='teacher', creator_teacher_id=teacher.id,
                         is_public=False, show_in_student=False, show_in_classroom=False)
        db.session.add_all([resource, other])
        db.session.commit()
        ids = {'teacher': teacher.id, 'student': student.id, 'class': cls.id,
               'resource': resource.id, 'other': other.id, 'root': root,
               'dir_name': dir_name}
    try:
        yield ids
    finally:
        with app.app_context():
            Resource.query.filter(Resource.id.in_([ids['resource'], ids['other']])).delete(
                synchronize_session=False)
            Student.query.filter_by(id=ids['student']).delete(synchronize_session=False)
            Teacher.query.filter_by(id=ids['teacher']).delete(synchronize_session=False)
            Class.query.filter_by(id=ids['class']).delete(synchronize_session=False)
            for key, value in saved.items():
                if value is None:
                    record = db.session.get(SystemConfig, key)
                    if record:
                        db.session.delete(record)
                else:
                    SystemConfig.set(key, value)
            db.session.commit()
            SystemConfig._invalidate_cache()
        shutil.rmtree(root, ignore_errors=True)


def _courseware_student_client(app, package):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(student_id=package['student'], student_name='课件学生')
    return client


def _courseware_ticket(client, package):
    response = client.get(f'/study/courseware-access/{package["resource"]}?file=pkg/index.html')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_signed_courseware_dependency_without_cookies(app, courseware_package):
    client = _courseware_student_client(app, courseware_package)
    ticket = _courseware_ticket(client, courseware_package)
    anon = app.test_client(use_cookies=False)
    static = f'/static/uploads/{courseware_package["dir_name"]}/pkg/data.json'
    assert anon.get(static, headers={'Origin': 'null'}).status_code == 403
    root = ticket['base_url']
    for path in ('pkg/index.html', 'pkg/sub.html', 'pkg/app.js', 'pkg/data.json'):
        response = anon.get(root + path, headers={'Origin': 'null'})
        assert response.status_code == 200, path
        assert response.headers['Access-Control-Allow-Origin'] == '*'
        assert 'Access-Control-Allow-Credentials' not in response.headers
        assert 'private' in response.headers['Cache-Control']
        assert 'no-store' in response.headers['Cache-Control']
        assert 'X-Frame-Options' not in response.headers
        assert 'frame-ancestors' not in response.headers.get(
            'Content-Security-Policy', '')
    html = anon.get(root + 'pkg/index.html').get_data(as_text=True)
    assert '<base href="' + root + 'pkg/index.html">' in html
    assert 'data-content-root="' + root + '"' in html
    assert 'data-token="' + ticket['bridge_token'] + '"' in html
    assert 'javascript' in anon.get(root + 'pkg/app.js').headers['Content-Type']
    assert anon.get(root + 'pkg/data.json').get_json() == {'map': 'history'}
    assert (courseware_package['root'] / 'pkg' / 'index.html').read_text(encoding='utf-8').startswith(
        '<html><head><meta charset="utf-8"><script type="module" src="app.js">')


def test_signed_courseware_rejects_hidden_and_cross_resource(app, courseware_package):
    client = _courseware_student_client(app, courseware_package)
    ticket = _courseware_ticket(client, courseware_package)
    root = ticket['base_url']
    anon = app.test_client(use_cookies=False)
    assert anon.get(root + 'pkg/hidden.html').status_code == 404
    for path in ('pkg/../index.html', 'pkg//index.html', 'pkg/data.json.',
                 'pkg/data.json::$DATA', 'pkg/PKG~1.JS', '.env', 'pkg/data.json.bak'):
        assert anon.get(root + path).status_code == 404, path
    other_root = root.rsplit(f'/{courseware_package["resource"]}/', 1)[0] + f'/{courseware_package["other"]}/'
    assert anon.get(other_root + 'pkg/sub.html').status_code == 404
    assert anon.post(root + 'pkg/data.json').status_code in (403, 405)
    bad = root.replace('/study/courseware-view/', '/study/courseware-view/invalid', 1)
    assert anon.get(bad + 'pkg/data.json').status_code == 404
    assert anon.get(f'/study/courseware-access/{courseware_package["resource"]}?file=pkg/index.html').status_code == 404


def test_anonymous_public_courseware_access_when_enabled(app, courseware_package):
    """公开上传资源允许匿名只读；非公开资源与关闭公开开关后仍拒绝。"""
    from app.extensions import cache as _cache
    with app.app_context():
        SystemConfig.set('courseware_public_enabled', 'true')
        db.session.commit()
        SystemConfig._invalidate_cache()
        _cache.clear()
    try:
        anon = app.test_client(use_cookies=False)
        resource_id = courseware_package['resource']
        other_id = courseware_package['other']
        resp = anon.get(
            f'/study/courseware-access/{resource_id}?file=pkg/index.html')
        assert resp.status_code == 200, resp.get_data(as_text=True)
        ticket = resp.get_json()
        root = ticket['base_url']
        for path in ('pkg/index.html', 'pkg/app.js', 'pkg/data.json'):
            sub = anon.get(root + path)
            assert sub.status_code == 200, path
            assert sub.headers['Access-Control-Allow-Origin'] == '*'
        assert anon.get(root + 'pkg/hidden.html').status_code == 404
        # 未对学生公开的同类上传资源仍不可匿名读取
        denied = anon.get(
            f'/study/courseware-access/{other_id}?file=pkg/sub.html')
        assert denied.status_code == 404
    finally:
        with app.app_context():
            SystemConfig.set('courseware_public_enabled', 'false')
            db.session.commit()
            SystemConfig._invalidate_cache()
            _cache.clear()


def test_allow_related_files_opens_hidden_dependencies_without_listing(
        app, courseware_package):
    """勾选“允许打开页面相关链接”后：隐藏子文件可读，但文件列表不变。"""
    from app.blueprints.resources import _build_study_resource_data
    from app.extensions import cache as _cache
    client = _courseware_student_client(app, courseware_package)
    root = _courseware_ticket(client, courseware_package)['base_url']
    dir_name = courseware_package['dir_name']
    static_hidden = f'/static/uploads/{dir_name}/pkg/hidden.html'
    try:
        assert client.get(root + 'pkg/hidden.html').status_code == 404
        assert client.get(static_hidden).status_code == 403
        with app.app_context():
            resource = db.session.get(Resource, courseware_package['resource'])
            resource.allow_related_files = True
            db.session.commit()
            _cache.delete('courseware:dir_map')
            data = _build_study_resource_data([resource])[0]
            visible = {f['name'] for f in data['visible_files']}
            assert 'pkg/index.html' in visible
            assert 'pkg/hidden.html' not in visible
        # 已有签名凭证无需重签：读取时按资源当前开关放行
        assert client.get(root + 'pkg/hidden.html').status_code == 200
        assert client.get(static_hidden).status_code == 200
    finally:
        with app.app_context():
            resource = db.session.get(Resource, courseware_package['resource'])
            if resource is not None:
                resource.allow_related_files = False
                db.session.commit()
            _cache.delete('courseware:dir_map')


def test_study_page_lazy_loads_file_grid(app, courseware_package):
    """学生首页不再内联扫描/渲染全部文件，展开资源时才请求文件网格。"""
    client = _courseware_student_client(app, courseware_package)
    rid = courseware_package['resource']
    page = client.get('/study').get_data(as_text=True)
    assert f'/study/resource/{rid}/files' in page
    assert 'pkg/index.html' not in page
    files_page = client.get(f'/study/resource/{rid}/files')
    assert files_page.status_code == 200
    body = files_page.get_data(as_text=True)
    assert 'study-files-fragment' in body and 'data-file-count=' in body
    assert 'pkg/index.html' in body
    other = client.get(
        f"/study/resource/{courseware_package['other']}/files")
    assert other.status_code == 404


def test_resource_forms_expose_allow_related_files():
    root = pathlib.Path(__file__).resolve().parent.parent
    edit = (root / 'templates' / 'edit_resource.html').read_text(
        encoding='utf-8')
    upload = (root / 'templates' / 'admin_resources_upload.html').read_text(
        encoding='utf-8')
    assert 'allow_related_files' in edit
    assert '允许打开页面相关链接' in edit
    assert 'allow_related_files' in upload
    assert '允许打开页面相关链接' in upload


def test_geogebra_cdn_loader_rewritten_to_local(tmp_path):
    """直接引用官方 deployggb.js 的课件改为随包副本，避免 CSP 拦截。"""
    root = tmp_path / 'resource'
    root.mkdir()
    html = ('<!doctype html><html><head>'
            '<script src="https://www.geogebra.org/apps/deployggb.js"></script>'
            '<script src="//www.geogebra.org/apps/deployggb.js"></script>'
            '<script>var s=document.createElement("script");'
            's.src="https://www.geogebra.org/apps/deployggb.js?v=2024";'
            'document.head.appendChild(s);</script>'
            '</head><body><div id="ggb-element"></div></body></html>')
    adapted, count = adapt_courseware_html(
        html, str(root), 'index.html', '资源目录')
    assert 'geogebra.org' not in adapted
    assert adapted.count('/static/geogebra/GeoGebra/deployggb.js') == 3
    assert count == 3


def test_geogebra_cdn_loader_rewritten_in_external_script(tmp_path):
    script = 'var u = "https://www.geogebra.org/apps/deployggb.js?v=1";'
    changed = adapt_courseware_script(
        script, str(tmp_path), 'app.js', 'resource',
        '/study/courseware-view/token/1/')
    assert changed == 'var u = "/static/geogebra/GeoGebra/deployggb.js";'


def test_bootstrap_forces_local_geogebra_engine_and_storage_shim():
    src = (pathlib.Path(__file__).resolve().parent.parent / 'static' / 'js'
           / 'ggb-courseware-bootstrap.js').read_text(encoding='utf-8')
    assert ("GGB_LOCAL_CODEBASE = "
            "'/static/geogebra/GeoGebra/HTML5/5.0/web3d/'") in src
    assert 'setHTML5Codebase' in src
    assert "shimStorage('localStorage')" in src
    assert "shimStorage('sessionStorage')" in src
    assert "HTMLImageElement.prototype, 'src'" in src
    assert "this.crossOrigin = 'anonymous'" in src


def test_worker_inlined_for_opaque_frames(tmp_path):
    root = tmp_path / 'resource'
    _write(root / 'pkg' / 'assets' / 'worker.js',
           '(function(){self.postMessage({ok:1});})();')
    script = ('const w=new Worker(new URL("/assets/worker.js",'
              'import.meta.url),{type:"module"});')
    changed = adapt_courseware_script(
        script, str(root), 'pkg/assets/app.js', 'resource',
        '/study/courseware-view/token/1/')
    # 不再内联：opaque 帧由桥接脚本经父页同源 Worker 中继；脚本中保留
    # 改写后的镜像 URL，供父页创建 Worker。
    assert 'new Worker(new URL(' in changed
    assert '/study/courseware-view/token/1/pkg/assets/worker.js' in changed



@pytest.mark.parametrize('change', ['deactivate', 'password', 'resource', 'file', 'class'])
def test_signed_courseware_rechecks_authorization(app, courseware_package, change):
    client = _courseware_student_client(app, courseware_package)
    root = _courseware_ticket(client, courseware_package)['base_url']
    with app.app_context():
        student = db.session.get(Student, courseware_package['student'])
        resource = db.session.get(Resource, courseware_package['resource'])
        if change == 'deactivate':
            student.is_activated = False
        elif change == 'password':
            student.set_password('ChangedCoursewarePass1')
        elif change == 'resource':
            resource.is_public = False
            resource.show_in_student = False
            resource.show_in_classroom = False
        elif change == 'file':
            resource.file_permissions = json.dumps({'pkg/data.json': {'show': False}})
        else:
            student.class_id = None
        db.session.commit()
        from app.extensions import cache as _cache
        _cache.clear()  # 模拟账号/授权写路径使短期读取缓存换代
    anon = app.test_client(use_cookies=False)
    assert anon.get(root + 'pkg/data.json').status_code == 404


def test_signed_courseware_expiration(app, courseware_package, monkeypatch):
    from itsdangerous.timed import TimestampSigner
    from app.blueprints.resources import _courseware_signer
    client = _courseware_student_client(app, courseware_package)
    root = _courseware_ticket(client, courseware_package)['base_url']
    token = root.split('/')[3]
    with app.app_context():
        signer = _courseware_signer()
        data = signer.loads(token)
        with monkeypatch.context() as patch:
            patch.setattr(TimestampSigner, 'get_timestamp', lambda self: int(time.time()) - 7200)
            expired = signer.dumps(data)
    expired_root = root.replace(token, expired)
    assert app.test_client(use_cookies=False).get(expired_root + 'pkg/data.json').status_code == 404


def test_study_link_issues_scoped_read_access(app, courseware_package):
    client = _courseware_student_client(app, courseware_package)
    response = client.get('/study/link?' + urlencode({
        'url': f'/static/uploads/{courseware_package["dir_name"]}/pkg/index.html?sample=1#demo',
        'resource_id': courseware_package['resource'],
    }))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    tag = re.search(r'<iframe id="mainFrame"[^>]*>', html).group(0)
    assert 'allow-same-origin' not in tag
    assert '/study/courseware-view/' in html and '"bridge_token"' in html
    assert '?sample=1#demo' in html


def test_courseware_frame_allows_data_script_modules(app, courseware_package):
    """三维课件常把 three.js 内联为 data:text/javascript 模块。

    仅镜像帧放行 data: 脚本（该帧已是无 Cookie 的 opaque sandbox），
    平台普通页面不扩大 CSP。
    """
    client = _courseware_student_client(app, courseware_package)
    root = _courseware_ticket(client, courseware_package)['base_url']
    anon = app.test_client(use_cookies=False)
    resp = anon.get(root + 'pkg/index.html')
    assert resp.status_code == 200
    csp = resp.headers.get('Content-Security-Policy', '')
    assert "script-src 'self' 'unsafe-inline' data:" in csp
    assert 'frame-ancestors' not in csp
    normal = client.get('/study').headers.get('Content-Security-Policy', '')
    assert 'data:' not in normal.split('script-src', 1)[1].split(';', 1)[0]


def test_study_link_back_avoids_iframe_joint_history():
    """课件 iframe 导航会污染联合会话历史，返回不能依赖 history.back()。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / 'templates' / 'study_link.html').read_text(encoding='utf-8')
    block = src[src.index('function goBack()'):
                src.index('function toggleFullscreen()')]
    assert 'history.back()' not in block
    assert "var target = '/study'" in block
    assert 'location.href = target' in block


def test_nginx_upload_proxy_precedes_nested_public_cache():
    path = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'itstudy.conf'
    text = path.read_text(encoding='utf-8')
    static = text.split('location /static/ {', 1)[1]
    assert static.index('location ~* ^/static/(submissions|homework|chunks|uploads)/') < static.index('location ~* /static/.*\\.html$')


def test_browser_router_window_adapter_does_not_change_hash_router(tmp_path):
    script = (
        'function createBrowserHistory(options={}){function read(w){'
        'let {pathname:p,search:s,hash:h}=w.location;return p;}return read;}'
        'function BrowserRouter({basename:b,children:c,window:w}){'
        'const history=createBrowserHistory({window:w,v5Compat:true});return c;}'
        'function HashRouter({basename:b,children:c,window:w}){'
        'const history=createHashHistory({window:w,v5Compat:true});return c;}')
    changed = adapt_courseware_script(script, str(tmp_path), 'assets/router.js',
                                      'resource', '/study/courseware-view/token/1/')
    assert 'w=w||globalThis.__ITSTUDY_COURSEWARE_ROUTER_WINDOW__;' in changed
    assert changed.count('__ITSTUDY_COURSEWARE_ROUTER_WINDOW__') == 1
    assert 'function HashRouter({basename:b,children:c,window:w}){const history=' in changed


def test_read_grant_maintenance_uses_signed_actor(app, courseware_package):
    student = _courseware_student_client(app, courseware_package)
    student_root = _courseware_ticket(student, courseware_package)['base_url']
    teacher = app.test_client()
    with teacher.session_transaction() as sess:
        sess.update(is_teacher=True, teacher_id=courseware_package['teacher'], teacher_mode='edit')
    teacher_root = _courseware_ticket(teacher, courseware_package)['base_url']
    with app.app_context():
        previous = db.session.get(SystemConfig, 'student_access_enabled')
        saved = previous.value if previous else None
        SystemConfig.set('student_access_enabled', 'false')
        db.session.commit()
        from app.extensions import cache as _cache
        _cache.clear()  # 模拟系统开关写路径使短期读取缓存换代
    try:
        anon = app.test_client(use_cookies=False)
        assert anon.get(student_root + 'pkg/data.json').status_code == 404
        assert anon.get(teacher_root + 'pkg/data.json').status_code == 200
    finally:
        with app.app_context():
            if saved is None:
                record = db.session.get(SystemConfig, 'student_access_enabled')
                if record:
                    db.session.delete(record)
            else:
                SystemConfig.set('student_access_enabled', saved)
            db.session.commit()
            SystemConfig._invalidate_cache()


@pytest.mark.parametrize('change', ['deactivate', 'readonly_code'])
def test_teacher_read_grant_revocation(app, courseware_package, change):
    from app.blueprints.auth import TEACHER_READONLY_CODE_KEY
    from app.utils import password_fingerprint
    with app.app_context():
        previous = db.session.get(SystemConfig, TEACHER_READONLY_CODE_KEY)
        saved = previous.value if previous else None
        SystemConfig.set(TEACHER_READONLY_CODE_KEY, 'readonly-code-test-hash')
        db.session.commit()
    try:
        teacher = app.test_client()
        with teacher.session_transaction() as sess:
            sess.update(is_teacher=True, teacher_id=courseware_package['teacher'], teacher_mode='readonly',
                        readonly_code_fp=password_fingerprint('readonly-code-test-hash'))
        root = _courseware_ticket(teacher, courseware_package)['base_url']
        anon = app.test_client(use_cookies=False)
        assert anon.get(root + 'pkg/data.json').status_code == 200
        with app.app_context():
            if change == 'deactivate':
                db.session.get(Teacher, courseware_package['teacher']).is_active = False
            else:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, 'changed-readonly-code-test-hash')
            db.session.commit()
            from app.extensions import cache as _cache
            _cache.clear()  # 模拟账号/只读访问码写路径使短期读取缓存换代
        assert anon.get(root + 'pkg/data.json').status_code == 404
    finally:
        with app.app_context():
            if saved is None:
                record = db.session.get(SystemConfig, TEACHER_READONLY_CODE_KEY)
                if record:
                    db.session.delete(record)
            else:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, saved)
            db.session.commit()
            SystemConfig._invalidate_cache()


def test_readonly_teacher_static_access_is_resource_scoped(app):
    """只读教师不能直读未授权上传目录；文件级隐藏同样生效。"""
    suffix = uuid.uuid4().hex[:8]
    dir_name = f'__ro_scoped_{suffix}'
    uploads = pathlib.Path(app.static_folder) / 'uploads'
    root = uploads / dir_name
    _write(root / 'main.html', '<html>main</html>')
    _write(root / 'secret.html', '<html>secret</html>')
    with app.app_context():
        config = db.session.get(SystemConfig, TEACHER_READONLY_CODE_KEY)
        saved = config.value if config else None
        SystemConfig.set(TEACHER_READONLY_CODE_KEY, 'readonly-scope-code')
        owner = Teacher(username=f'__ro_owner_{suffix}', display_name='只读资源教师')
        owner.set_password('ReadonlyPass1')
        other = Teacher(username=f'__ro_other_{suffix}', display_name='无权限教师')
        other.set_password('ReadonlyPass1')
        db.session.add_all([owner, other])
        db.session.flush()
        resource = Resource(
            title=dir_name, url=f'/static/uploads/{dir_name}/main.html',
            creator_type='teacher', creator_teacher_id=owner.id,
            is_public=False, show_in_student=False, show_in_classroom=False,
            file_permissions=json.dumps({'secret.html': {'show': False}}))
        db.session.add(resource)
        db.session.commit()
        ids = {'owner': owner.id, 'other': other.id, 'resource': resource.id}

    def client_for(teacher_id, mode='readonly'):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess.update(is_teacher=True, teacher_id=teacher_id,
                        teacher_mode=mode,
                        readonly_code_fp=password_fingerprint(
                            'readonly-scope-code'))
        return client

    try:
        owner = client_for(ids['owner'])
        assert owner.get(f'/static/uploads/{dir_name}/main.html').status_code == 200
        assert owner.get(f'/static/uploads/{dir_name}/secret.html').status_code == 403
        no_access = client_for(ids['other'])
        assert no_access.get(f'/static/uploads/{dir_name}/main.html').status_code == 403
        editor = client_for(ids['other'], mode='edit')
        assert editor.get(f'/static/uploads/{dir_name}/main.html').status_code == 200
        assert editor.get(f'/static/uploads/{dir_name}/secret.html').status_code == 200
    finally:
        with app.app_context():
            Resource.query.filter_by(id=ids['resource']).delete(
                synchronize_session=False)
            Teacher.query.filter(Teacher.id.in_(
                [ids['owner'], ids['other']])).delete(synchronize_session=False)
            if saved is None:
                record = db.session.get(SystemConfig, TEACHER_READONLY_CODE_KEY)
                if record:
                    db.session.delete(record)
            else:
                SystemConfig.set(TEACHER_READONLY_CODE_KEY, saved)
            db.session.commit()
            SystemConfig._invalidate_cache()
            from app.extensions import cache as _cache
            _cache.delete('courseware:dir_map')
        shutil.rmtree(root, ignore_errors=True)
