"""安全辅助函数回归测试：SSRF 校验、parse_int、管理员登录限流。

SSRF 用例仅用 IP 字面量 / localhost（离线可判定），避免依赖外网 DNS 造成 flaky。
"""
import pytest
from flask import Flask

from app import create_app
from app.extensions import db
from app.blueprints.ai import _is_safe_outbound_url as safe, _valid_session_id
from app.blueprints import auth as auth_blueprint
from app.utils import (
    parse_int,
    read_admin_account,
    verify_admin_account,
    admin_login_blocked_seconds,
    admin_login_register_failure,
    admin_login_register_success,
    all_chunks_present,
    generate_numeric_password,
)
from app.config import _deploy_int


def test_deploy_int_falls_back_on_invalid_value(monkeypatch):
    """deploy.conf 的整型参数误填时不得在导入期崩溃（回退默认值）。"""
    monkeypatch.delenv('ITSTUDY_TEST_INT', raising=False)
    assert _deploy_int({}, 'ITSTUDY_TEST_INT', 'test_int', 16) == 16
    assert _deploy_int({'test_int': 'abc'}, 'ITSTUDY_TEST_INT', 'test_int', 16) == 16
    assert _deploy_int({'test_int': '0'}, 'ITSTUDY_TEST_INT', 'test_int', 16) == 16
    assert _deploy_int({'test_int': '20'}, 'ITSTUDY_TEST_INT', 'test_int', 16) == 20
    monkeypatch.setenv('ITSTUDY_TEST_INT', '32')
    assert _deploy_int({'test_int': '20'}, 'ITSTUDY_TEST_INT', 'test_int', 16) == 32


def test_admin_plaintext_account_is_migrated_to_hash(tmp_path, monkeypatch):
    account_file = tmp_path / 'admin_account.txt'
    account_file.write_text('root\nsecret123\n', encoding='utf-8')
    monkeypatch.setattr('app.utils.get_admin_account_file', lambda: str(account_file))

    username, password_hash = read_admin_account()

    assert username == 'root'
    assert password_hash.startswith(('scrypt:', 'pbkdf2:'))
    assert 'secret123' not in account_file.read_text(encoding='utf-8')
    ok, _ = verify_admin_account('root', 'secret123')
    assert ok is True
    assert verify_admin_account('root', 'wrong')[0] is False


def _clear_admin_table_account(app):
    """测试库中是否有同名表账号会遮蔽文件账号兜底（不应存在）。"""
    from app.models import AdminAccount
    from app.extensions import db
    with app.app_context():
        AdminAccount.query.filter_by(username='admin').delete(synchronize_session=False)
        db.session.commit()


def test_admin_initial_password_file_created_and_consumed(app, tmp_path, monkeypatch):
    """服务方式安装没有可读控制台：随机初始密码必须落一次性提示文件，
    首次管理员登录成功后删除（否则全新装机无法完成首次登录）。"""
    import app.utils as utils_module
    account_file = tmp_path / 'admin_account.txt'
    monkeypatch.setattr('app.utils.get_admin_account_file', lambda: str(account_file))
    monkeypatch.delenv('ADMIN_INIT_PASSWORD', raising=False)
    utils_module._admin_cache.update(path=None, mtime=0, username=None, password_hash=None)
    _clear_admin_table_account(app)

    username, _ = read_admin_account()
    initial_file = tmp_path / 'admin_account.initial.txt'
    assert username == 'admin'
    assert initial_file.exists(), '随机初始密码必须可通过提示文件获取'
    password = initial_file.read_text(encoding='utf-8').strip()
    assert password, '提示文件不应为空'

    # 错误密码不消费提示文件
    assert verify_admin_account('admin', 'wrong-password')[0] is False
    assert initial_file.exists()

    # 正确密码登录成功后提示文件自动删除
    assert verify_admin_account('admin', password)[0] is True
    assert not initial_file.exists(), '首次登录成功后应删除一次性提示文件'


def test_admin_preset_password_does_not_write_plaintext_file(app, tmp_path, monkeypatch):
    """ADMIN_INIT_PASSWORD 预置密码时不产生明文提示文件。"""
    import app.utils as utils_module
    account_file = tmp_path / 'admin_account.txt'
    monkeypatch.setattr('app.utils.get_admin_account_file', lambda: str(account_file))
    monkeypatch.setenv('ADMIN_INIT_PASSWORD', 'preset-pass-123')
    utils_module._admin_cache.update(path=None, mtime=0, username=None, password_hash=None)
    _clear_admin_table_account(app)

    username, _ = read_admin_account()
    assert username == 'admin'
    assert not (tmp_path / 'admin_account.initial.txt').exists()
    assert verify_admin_account('admin', 'preset-pass-123')[0] is True


def test_admin_account_path_env_override_persists_in_volume(app, tmp_path, monkeypatch):
    """容器部署把账号文件指到持久卷：容器重建后改过的密码仍然有效。

    compose 设 ADMIN_ACCOUNT_FILE=/app/instance/admin_account.txt；默认的
    项目根目录不在任何卷内，重建容器会重新生成随机密码。
    """
    import app.utils as utils_module
    target = tmp_path / 'instance' / 'admin_account.txt'
    target.parent.mkdir()
    monkeypatch.setenv('ADMIN_ACCOUNT_FILE', str(target))
    monkeypatch.setenv('ADMIN_INIT_PASSWORD', 'volume-pass-123')
    utils_module._admin_cache.update(path=None, mtime=0, username=None, password_hash=None)
    _clear_admin_table_account(app)

    username, _ = read_admin_account()
    assert username == 'admin'
    assert target.exists(), 'ADMIN_ACCOUNT_FILE 指定的位置必须真正写入'
    assert not (tmp_path / 'admin_account.txt').exists()
    assert verify_admin_account('admin', 'volume-pass-123')[0] is True
    # 不把临时路径留在进程级缓存里（后续用例会读真实/自建账号文件）
    utils_module._admin_cache.update(path=None, mtime=0, username=None, password_hash=None)


def test_ssrf_blocks_dangerous_targets():
    # 云元数据 / 回环 / 未指定 / 非 http 协议 / 空
    assert safe('http://169.254.169.254/latest/meta-data/') is False
    assert safe('http://127.0.0.1:11434/v1') is False
    assert safe('http://localhost/v1') is False
    assert safe('http://0.0.0.0/') is False
    assert safe('ftp://example.com/') is False
    assert safe('file:///etc/passwd') is False
    assert safe('') is False
    assert safe('not a url') is False


def test_ssrf_private_network_requires_explicit_allowlist():
    assert safe('http://192.168.1.50:8000/v1') is False
    assert safe('http://10.0.0.8/v1') is False

    app = Flask(__name__)
    app.config['STUDENT_AI_PRIVATE_HOSTS'] = {'192.168.1.50'}
    with app.app_context():
        assert safe('http://192.168.1.50:8000/v1') is True
        assert safe('http://10.0.0.8/v1') is False


def test_ssrf_allowlist_supports_host_port_format():
    """回归：白名单条目带端口（deploy.conf 示例 host:port）时也应放行。"""
    app = Flask(__name__)
    app.config['STUDENT_AI_PRIVATE_HOSTS'] = {'192.168.1.50:8000'}
    with app.app_context():
        assert safe('http://192.168.1.50:8000/v1') is True
        assert safe('http://10.0.0.8/v1') is False


def test_ssrf_blocks_ipv4_mapped_loopback():
    """回归：IPv4-mapped IPv6（::ffff:127.0.0.1）按 IPv4 语义判为回环并拒绝。"""
    assert safe('http://[::ffff:127.0.0.1]:8000/v1') is False


def test_ai_session_id_is_bounded_and_character_restricted():
    assert _valid_session_id('abc_DEF-123') is True
    assert _valid_session_id('') is False
    assert _valid_session_id('../other-session') is False
    assert _valid_session_id('a' * 51) is False


def test_parse_int():
    assert parse_int('5') == 5
    assert parse_int('  7 ') == 7
    assert parse_int('abc') is None
    assert parse_int('') is None
    assert parse_int(None) is None
    assert parse_int('abc', 0) == 0
    assert parse_int(12) == 12


def test_generated_temporary_password_is_unpredictable_shape():
    first = generate_numeric_password()
    assert len(first) == 8 and first.isdigit()


def test_chunk_completion_is_independent_of_arrival_order(tmp_path):
    (tmp_path / '2').write_bytes(b'c')
    (tmp_path / '0').write_bytes(b'a')
    assert all_chunks_present(str(tmp_path), 3) is False
    (tmp_path / '1').write_bytes(b'b')
    assert all_chunks_present(str(tmp_path), 3) is True


def test_admin_login_throttle():
    ip = '203.0.113.77'
    admin_login_register_success(ip)  # 确保干净起点
    assert admin_login_blocked_seconds(ip) == 0
    for _ in range(7):
        admin_login_register_failure(ip)
    assert admin_login_blocked_seconds(ip) == 0  # 7 次未达阈值
    remaining = admin_login_register_failure(ip)  # 第 8 次触发封锁
    assert remaining > 0
    assert admin_login_blocked_seconds(ip) > 0
    admin_login_register_success(ip)  # 成功登录清除封锁
    assert admin_login_blocked_seconds(ip) == 0


def test_student_login_throttle_account_dimension():
    """学生登录限流：单账号 8 次失败封锁；同 IP 其他账号不受账号维度影响。"""
    from app.utils import (
        student_login_blocked_seconds, student_login_register_failure,
        student_login_register_success,
    )
    ip = '203.0.113.210'
    student_login_register_success(ip, '2026001')
    student_login_register_success(ip, '2026002')
    assert student_login_blocked_seconds(ip, '2026001') == 0
    for _ in range(7):
        student_login_register_failure(ip, '2026001')
    assert student_login_blocked_seconds(ip, '2026001') == 0  # 7 次未达阈值
    assert student_login_register_failure(ip, '2026001') > 0  # 第 8 次封锁
    assert student_login_blocked_seconds(ip, '2026001') > 0
    assert student_login_blocked_seconds(ip, '2026002') == 0  # 其他账号不受影响
    student_login_register_success(ip, '2026001')
    assert student_login_blocked_seconds(ip, '2026001') == 0  # 登录成功解除


def test_student_login_throttle_ip_global_dimension():
    """学生登录限流：IP 全局 50 次失败封锁，防横向枚举全班账号。"""
    from app.utils import (
        student_login_blocked_seconds, student_login_register_failure,
    )
    ip = '203.0.113.211'
    for i in range(49):
        student_login_register_failure(ip, f'stu{i}')
    # 每个账号都远未到 8 次，但 IP 全局累计 49 次尚未达 50 阈值
    assert student_login_blocked_seconds(ip, 'stu0') == 0
    assert student_login_register_failure(ip, 'stu49') > 0  # 第 50 次触发全局封锁
    assert student_login_blocked_seconds(ip, 'stu0') > 0    # 任意账号均被封锁


def test_name_login_limits_candidates_to_active_class(monkeypatch):
    class Candidate:
        def __init__(self, student_id, class_id, password):
            self.id = student_id
            self.class_id = class_id
            self.password = password
            self.is_activated = True
            self.name = '同名学生'
            self.ip_address = None
            self.login_time = None
            self.last_seen = None

        def check_password(self, value):
            return value == self.password

    in_class = Candidate(2, 20, 'correct')
    out_of_class = Candidate(1, 10, 'correct')

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **kwargs):
            return Query([
                row for row in self.rows
                if all(getattr(row, key) == value for key, value in kwargs.items())
            ])

        def filter(self, criterion):
            # 仅用于测试 Student.class_id.in_(id_set)
            allowed = set(criterion.right.value)
            return Query([row for row in self.rows
                          if row.class_id in allowed])

        def all(self):
            return self.rows

    class FakeColumn:
        def in_(self, values):
            class Expr:
                right = type('Right', (), {'value': tuple(values)})()
            return Expr()

    class FakeStudentModel:
        query = Query([out_of_class, in_class])
        class_id = FakeColumn()

    monkeypatch.setattr(auth_blueprint, 'Student', FakeStudentModel)
    monkeypatch.setattr(auth_blueprint.db.session, 'commit', lambda: None)

    ok, _, student = auth_blueprint._authenticate_student_by_field(
        'name', in_class.name, 'correct', 20, '203.0.113.1'
    )

    assert ok is True
    assert student is in_class


# ── 管理员多账号保护逻辑（V5.0）──

@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        from app.models import AdminAccount
        AdminAccount.query.delete(synchronize_session=False)
        db.session.commit()


def _make_admin(app, username, display_name=None, password='pass123'):
    from app.models import AdminAccount
    with app.app_context():
        acct = AdminAccount(username=username, display_name=display_name or username)
        acct.set_password(password)
        db.session.add(acct)
        db.session.commit()
        return acct.id


def test_admin_self_protection_uses_account_id(app):
    """自我保护按账号 id 判定：显示名与用户名不一致时不能停用/删除自己"""
    from app.models import AdminAccount
    from app.extensions import db
    aid = _make_admin(app, 'wang', display_name='王老师')
    try:
        client = app.test_client()
        with client.session_transaction() as s:
            s['is_admin'] = True
            s['admin_name'] = '王老师'          # 显示名
            s['admin_account_id'] = aid         # 账号 id
            s['csrf_token'] = 't'
        client.post('/admin/accounts', data={'action': 'toggle', 'account_id': str(aid)},
                    headers={'X-CSRFToken': 't'}, follow_redirects=True)
        with app.app_context():
            acct = db.session.get(AdminAccount, aid)
            assert acct.is_active is True, '显示名≠用户名时应拒绝停用自己'
        client.post('/admin/accounts', data={'action': 'delete', 'account_id': str(aid)},
                    headers={'X-CSRFToken': 't'}, follow_redirects=True)
        with app.app_context():
            assert db.session.get(AdminAccount, aid) is not None, '应拒绝删除自己'
        print('自我保护（显示名≠用户名）OK')
    finally:
        with app.app_context():
            AdminAccount.query.filter_by(username='wang').delete(synchronize_session=False)
            db.session.commit()


def test_admin_toggle_keeps_one_active(app):
    """toggle 与 delete 都保留至少一个启用账号"""
    from app.models import AdminAccount
    from app.extensions import db
    aid1 = _make_admin(app, 'acc_a', '账号A')
    aid2 = _make_admin(app, 'acc_b', '账号B')
    try:
        client = app.test_client()
        with client.session_transaction() as s:
            s['is_admin'] = True
            s['admin_account_id'] = aid1
            s['csrf_token'] = 't'
        # 停用 B（此时 A 启用）→ 允许
        client.post('/admin/accounts', data={'action': 'toggle', 'account_id': str(aid2)},
                    headers={'X-CSRFToken': 't'}, follow_redirects=True)
        # 停用 A（此时只剩 B 启用？不——A 是自己不能停；再启用 B 后停用 A 仍被拒）
        with app.app_context():
            b = db.session.get(AdminAccount, aid2)
            assert b.is_active is False
        # 尝试停用唯一启用的 A（自己）→ 拒绝
        client.post('/admin/accounts', data={'action': 'toggle', 'account_id': str(aid1)},
                    headers={'X-CSRFToken': 't'}, follow_redirects=True)
        with app.app_context():
            a = db.session.get(AdminAccount, aid1)
            assert a.is_active is True
        print('toggle 保护 OK')
    finally:
        with app.app_context():
            AdminAccount.query.filter(AdminAccount.id.in_([aid1, aid2])).delete(synchronize_session=False)
            db.session.commit()


def test_inactive_table_account_does_not_shadow_file(app):
    """被停用的表账号不遮蔽同名文件账号（文件兜底仍可登录）"""
    from app.models import AdminAccount
    from app.extensions import db
    from app.utils import verify_admin_account
    # 表账号 admin 停用（文件账号 admin 存在时）
    aid = _make_admin(app, 'admin', '表admin')
    try:
        with app.app_context():
            acct = db.session.get(AdminAccount, aid)
            acct.is_active = False
            db.session.commit()
        # 文件账号 admin（真实密码未知）→ verify 走文件分支返回 (False, ('file', None))
        # 不因表账号停用而提前拒绝为 ('inactive', ...)
        ok, info = verify_admin_account('admin', 'wrong-password')
        assert info[0] == 'file', '停用表账号后应回退文件兜底而非 inactive 拒绝'
        assert ok is False, '错误密码应拒绝'
        print('停用遮蔽修复 OK')
    finally:
        with app.app_context():
            AdminAccount.query.filter_by(username='admin').delete(synchronize_session=False)
            db.session.commit()
