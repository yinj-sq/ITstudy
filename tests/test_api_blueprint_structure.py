from flask import Flask
import ast
from pathlib import Path

from app.blueprints.api import api_bp


def test_split_api_modules_register_expected_routes():
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert len(api_bp.deferred_functions) >= 49
    assert '/api/auth/login' in rules
    assert '/api/exams' in rules
    assert '/api/questions' in rules
    assert '/api/resources' in rules
    assert '/api/results/<int:result_id>' in rules
    assert '/api/management/students' in rules
    assert '/api/groups' in rules
    assert '/api/attendance/status' in rules


def test_write_routes_are_protected_except_authentication_entrypoints():
    anonymous_writes = {
        'auth_login', 'auth_admin_login', 'auth_logout',
        'login', 'admin_login', 'teacher_login',
    }
    violations = []
    for path in Path('app/blueprints').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            decorators = [ast.unparse(item) for item in node.decorator_list]
            routes = [item for item in decorators if '.route(' in item]
            is_write = routes and any(
                method in ' '.join(routes)
                for method in ("'POST'", "'PUT'", "'PATCH'", "'DELETE'")
            )
            protected = any('required' in item for item in decorators)
            if is_write and not protected and node.name not in anonymous_writes:
                violations.append(f'{path.name}:{node.name}')
    assert violations == []
