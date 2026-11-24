import os
from types import SimpleNamespace

import pytest

from app.blueprints.homework import _safe_file_under
from app.blueprints.resources import _resource_subject_id
from app.filters import convert_md_images
from app.models import _quote_sql_identifier, PythonFile, PythonAnswer, GroupFile, Student
from app.utils import safe_inline_mimetype, secure_filename_with_unicode
from app.blueprints import ai as ai_blueprint


def test_sql_identifier_quote_rejects_unsafe_names():
    assert _quote_sql_identifier('student_drive_file') == '"student_drive_file"'
    assert _quote_sql_identifier('col_1') == '"col_1"'

    for value in ['student;drop', 'has-dash', '1starts_with_digit', '', None]:
        with pytest.raises(ValueError):
            _quote_sql_identifier(value)


def test_safe_file_under_blocks_traversal(tmp_path):
    base = tmp_path / 'homework'
    nested = base / 'nested'
    nested.mkdir(parents=True)
    target = nested / 'ok.txt'
    target.write_text('ok', encoding='utf-8')

    assert _safe_file_under(str(base), 'nested/ok.txt') == os.path.realpath(target)
    assert _safe_file_under(str(base), '../secret.txt') is None
    assert _safe_file_under(str(base), 'nested/../../secret.txt') is None
    assert _safe_file_under(str(base), '') is None


def test_resource_subject_id_supports_cached_dict_and_model_like_object():
    assert _resource_subject_id({'res': {'subject_id': 3}}) == 3
    assert _resource_subject_id({'res': SimpleNamespace(subject_id=4)}) == 4
    assert _resource_subject_id({'res': {}}) is None
    assert _resource_subject_id({}) is None


def test_convert_md_images_escapes_dangerous_urls():
    safe = str(convert_md_images('![alt](/static/question_img/a.png)'))
    assert '<img' in safe
    assert 'src="/static/question_img/a.png"' in safe
    assert 'alt="alt"' in safe

    bad = str(convert_md_images('![x](javascript:alert(1))'))
    assert '<img' not in bad
    assert 'javascript:alert(1)' in bad


def test_secure_filename_with_unicode_strips_path_separators():
    for value in ['../a/b.py', '..\\a\\b.py', '../../secret.txt']:
        safe = secure_filename_with_unicode(value)
        assert '/' not in safe
        assert '\\' not in safe
        assert '..' not in safe
        assert safe.endswith(('.py', '.txt'))


def test_safe_inline_mimetype_forces_active_content_to_text():
    assert safe_inline_mimetype('index.html') == 'text/plain; charset=utf-8'
    assert safe_inline_mimetype('script.js') == 'text/plain; charset=utf-8'
    assert safe_inline_mimetype('image.png') is None


def test_model_file_read_helpers_use_module_level_os(tmp_path):
    text_file = tmp_path / 'answer.py'
    text_file.write_text('print(1)', encoding='utf-8')
    binary_file = tmp_path / 'group.bin'
    binary_file.write_bytes(b'abc')

    assert PythonFile(file_path='answer.py').read_content(str(tmp_path)) == 'print(1)'
    assert PythonAnswer(file_path='answer.py').read_content(str(tmp_path)) == 'print(1)'
    assert GroupFile(file_path='group.bin').read_content(str(tmp_path)) == b'abc'


def test_student_model_has_no_plaintext_password_column():
    assert not hasattr(Student, 'plain_password')


def test_ai_outbound_requests_do_not_follow_redirects(monkeypatch):
    seen = {}

    class Response:
        status_code = 302

    def fake_request(method, url, **kwargs):
        seen['method'] = method
        seen['url'] = url
        seen.update(kwargs)
        return Response()

    # 管理端配置（needs_dns_pinning=False）走 http_requests.request
    monkeypatch.setattr(ai_blueprint.http_requests, 'request', fake_request)
    ok, _ = ai_blueprint._fetch_models('openai', 'key', 'https://example.com/v1')

    assert ok is False
    assert seen['method'] == 'GET'
    assert seen['allow_redirects'] is False
