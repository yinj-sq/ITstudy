"""数据库敏感凭据加密。

密钥由持久化 SECRET_KEY 和固定用途标签派生，数据库备份本身不包含解密密钥。
密文带版本前缀，便于后续轮换算法；无前缀值视为旧版明文并由启动迁移处理。
"""
import base64
import functools
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Config


_PREFIX = 'enc:v1:'
_CONTEXT = b'ITstudy/AI-credentials/v1\0'


@functools.lru_cache(maxsize=8)
def _derive_key(secret, kdf=True):
    """从 SECRET_KEY 派生 Fernet 密钥（按 secret 缓存）。

    kdf=True：PBKDF2-HMAC-SHA256（100k 轮，抗离线爆破）；
    kdf=False：旧版单次 SHA-256（仅用于存量密文解密回退）。
    100k 轮单次约 80ms：不缓存时每读一次 api_key 都要付一遍，匿名可达的
    /api/ai/status 每秒十来个请求就能占满一个 CPU 核。
    """
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    if kdf:
        derived = hashlib.pbkdf2_hmac('sha256', secret, _CONTEXT, 100_000)
    else:
        derived = hashlib.sha256(_CONTEXT + bytes(secret)).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _fernet():
    return _derive_key(Config.SECRET_KEY, kdf=True)


def _legacy_fernet():
    return _derive_key(Config.SECRET_KEY, kdf=False)


def is_encrypted_secret(value):
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_secret(value):
    if value is None or value == '':
        return value
    value = str(value)
    if is_encrypted_secret(value):
        return value
    token = _fernet().encrypt(value.encode('utf-8')).decode('ascii')
    return _PREFIX + token


def decrypt_secret(value):
    if value is None or value == '':
        return value
    value = str(value)
    if not is_encrypted_secret(value):
        return value
    payload = value[len(_PREFIX):].encode('ascii')
    try:
        return _fernet().decrypt(payload).decode('utf-8')
    except (InvalidToken, ValueError, UnicodeError):
        pass
    # 存量密文回退：此前为单次 SHA-256 派生，SECRET_KEY 未更换时旧密文
    # 仍可解密；两者都失败才是密钥被更换。
    try:
        return _legacy_fernet().decrypt(payload).decode('utf-8')
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ValueError('AI 凭据无法解密，请确认 SECRET_KEY 未被更换') from exc

