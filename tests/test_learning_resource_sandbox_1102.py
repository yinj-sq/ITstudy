# -*- coding: utf-8 -*-
"""学习资源 iframe sandbox 回归（2026-11-02）。

活动单类 HTML 资源在 iframe 内需要 allow-downloads（导出/下载）与
allow-modals（打印/保存为 PDF）；study_link 仍不得授予 allow-same-origin。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _iframe_tag(src, frame_id):
    m = re.search(rf'<iframe id="{frame_id}"[^>]*>', src)
    assert m, f'{frame_id} iframe 未找到'
    return m.group(0)


def test_study_link_sandbox_allows_download_and_print_without_same_origin():
    tag = _iframe_tag(_read('templates/study_link.html'), 'mainFrame')
    assert 'allow-downloads' in tag
    assert 'allow-modals' in tag
    # 仅站内受信 GeoGebra 播放器条件放行 allow-same-origin；
    # 外部/普通课件仍为 opaque origin。
    trusted = '{% if trusted_same_origin %} allow-same-origin{% endif %}'
    assert trusted in tag
    assert 'allow-same-origin' not in tag.replace(trusted, '')


def test_study_lesson_link_frame_is_opaque_for_uploads():
    """课堂上传统上传 HTML 不得同源执行；仅平台页面由脚本动态放行。"""
    src = _read('templates/study_lesson.html')
    tag = _iframe_tag(src, 'linkFrame')
    assert 'allow-same-origin' not in tag
    js = _read('static/js/study_lesson.js')
    assert 'setLinkFrameSandbox' in js
    assert 'isTrustedLinkSource' in js
    assert 'allow-same-origin' in js


def test_courseware_worker_relay_present():
    relay = _read('static/js/courseware-worker-relay.js')
    assert 'ITSTUDY_WORKER_CREATE' in relay
    assert 'ITSTUDY_WORKER_MESSAGE' in relay
    assert 'ITSTUDY_WORKER_TERMINATE' in relay
    bootstrap = _read('static/js/ggb-courseware-bootstrap.js')
    assert 'ITSTUDY_WORKER_CREATE' in bootstrap
    assert "location.origin === 'null'" in bootstrap
    assert 'randomUUID' in bootstrap and 'getRandomValues' in bootstrap
    assert 'courseware-worker-relay.js' in _read('templates/study_lesson.html')
    assert 'courseware-worker-relay.js' in _read('templates/study_link.html')
    assert 'setupCoursewareWorkerRelay' in _read('static/js/study_lesson.js')


def test_study_lesson_frames_allow_downloads():
    src = _read('templates/study_lesson.html')
    for frame_id in ('linkFrame', 'docFrame', 'pptistFrame'):
        tag = _iframe_tag(src, frame_id)
        assert 'allow-downloads' in tag, frame_id


def test_document_preview_html_sandbox_allows_download_and_print():
    src = _read('templates/document_preview.html')
    assert "sandbox', 'allow-scripts allow-downloads allow-modals'" in src
    assert 'allow-same-origin' not in src.split('renderSandboxedHtml')[1].split('function renderSpreadsheet')[0]
