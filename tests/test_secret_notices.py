from flask import Flask

from app.blueprints import class_management


def test_password_notice_is_server_side_and_one_time(monkeypatch):
    values = {}
    monkeypatch.setattr(class_management.cache, 'set', lambda key, value, timeout: values.__setitem__(key, value))
    monkeypatch.setattr(class_management.cache, 'get', lambda key: values.get(key))
    monkeypatch.setattr(class_management.cache, 'delete', lambda key: values.pop(key, None))

    token = class_management._store_secret_notice('temporary-password')
    app = Flask(__name__)
    with app.test_request_context(f'/?secret_notice={token}'):
        assert class_management._consume_secret_notice() == 'temporary-password'
        assert class_management._consume_secret_notice() is None
