# -*- coding: utf-8 -*-
"""外链资源课堂模式回归（2026-11-24）。

外链资源没有本地文件，课堂页默认章节树此前为空；同时 /study 外链分支
没有“进入课堂”入口。这里覆盖默认外链条目、页面入口与课堂沙箱权限。
"""
import pathlib
import uuid

import pytest

from app import create_app
from app.blueprints.resources import _default_lesson_tree
from app.extensions import db
from app.models import Resource

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def app():
    application = create_app()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def test_default_lesson_tree_includes_external_resource():
    tree = _default_lesson_tree(
        [], [], external_url='https://example.com/demo',
        external_title='示例外链')
    assert tree and tree[0]['title'] == '课程内容'
    item = tree[0]['items'][0]
    assert item['kind'] == 'link'
    assert item['src'] == 'https://example.com/demo'
    assert item['title'] == '示例外链'
    assert item['visible'] == {'teacher': True, 'student': True}


def test_study_lesson_renders_external_default_item(app):
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        resource = Resource(
            title=f'外链课堂_{suffix}',
            url='https://example.com/demo',
            show_in_student=True,
            show_in_classroom=True)
        db.session.add(resource)
        db.session.commit()
        resource_id = resource.id
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess.update(is_admin=True, admin_name='外链课堂测试')
        response = client.get(f'/study/lesson/{resource_id}')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'https://example.com/demo' in html
        # 默认章节树里外链是一个 kind=link 条目
        assert '"kind": "link"' in html
    finally:
        with app.app_context():
            Resource.query.filter_by(id=resource_id).delete(
                synchronize_session=False)
            db.session.commit()


def test_external_resource_study_page_exposes_classroom_entry():
    src = (ROOT / 'templates' / 'study.html').read_text(encoding='utf-8')
    marker = '{% elif rd.is_external_link %}'
    starts = [i for i in range(len(src)) if src.startswith(marker, i)]
    start = next(i for i in starts if 'p-3 bg-light' in src[i:i + 200])
    end = src.index('{% elif rd.is_file_resource %}', start)
    block = src[start:end]
    assert '打开（新标签页）' in block
    assert 'href="{{ res.url }}" target="_blank"' in block
    assert '站内打开（含 AI 助手）' in block
    assert '进入课堂' in block
    assert '/study/lesson/{{ res.id }}' in block


def test_nginx_sample_sends_proxy_secret_and_forwarded_headers():
    conf = (ROOT / 'docs' / 'itstudy.conf').read_text(encoding='utf-8')
    assert 'proxy_set_header X-Real-IP $remote_addr;' in conf
    assert 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' in conf
    secret_lines = [line.strip() for line in conf.splitlines()
                    if 'proxy_set_header X-Proxy-Secret' in line]
    assert secret_lines and not secret_lines[0].startswith('#'), secret_lines


def test_classroom_external_link_has_new_tab_escape():
    html = (ROOT / 'templates' / 'study_lesson.html').read_text(encoding='utf-8')
    assert 'id="externalOpen"' in html
    js = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    assert 'externalOpen' in js
    assert 'isExternalLinkSource(originalSrc)' in js


def test_classroom_sandbox_allows_external_user_navigation():
    js = (ROOT / 'static' / 'js' / 'study_lesson.js').read_text(encoding='utf-8')
    assert 'isExternalLinkSource' in js
    assert 'allow-top-navigation-by-user-activation' in js
    assert 'allow-popups-to-escape-sandbox' in js
    # 上传课件/平台页面仍保持严格沙箱：权限只在外部源分支追加
    assert "else if (isExternalLinkSource(src))" in js
