from pathlib import Path


def test_alembic_url_rendering_hides_database_password():
    source = Path('migrations/env.py').read_text(encoding='utf-8')
    assert 'get_engine_url(hide_password=not context.is_offline_mode())' in source
    assert 'render_as_string(hide_password=hide_password)' in source


def test_proxy_headers_require_explicit_opt_in():
    source = Path('app/__init__.py').read_text(encoding='utf-8')
    assert 'if Config.TRUST_PROXY_HEADERS:' in source
    assert 'if Config.TRUSTED_HOSTS:' not in source
