from app.credential_crypto import decrypt_secret, encrypt_secret, is_encrypted_secret
from app import models
from app.models import AIConfig, StudentAIConfig, TeacherAIConfig, AIImageConfig


def test_secret_round_trip_and_no_plaintext_at_rest():
    encrypted = encrypt_secret('sk-sensitive-value')

    assert is_encrypted_secret(encrypted)
    assert 'sk-sensitive-value' not in encrypted
    assert decrypt_secret(encrypted) == 'sk-sensitive-value'


def test_legacy_plaintext_is_readable_for_startup_migration():
    assert decrypt_secret('legacy-key') == 'legacy-key'


def test_ai_models_encrypt_api_key_on_assignment():
    for config in (AIConfig(), StudentAIConfig(student_id=1),
                   TeacherAIConfig(teacher_id=1), AIImageConfig()):
        config.api_key = 'secret-key'
        assert config.api_key == 'secret-key'
        assert config._api_key != 'secret-key'
        assert is_encrypted_secret(config._api_key)


def test_startup_migration_encrypts_legacy_rows(monkeypatch):
    legacy_admin = type('Row', (), {'_api_key': 'admin-plain'})()
    legacy_student = type('Row', (), {'_api_key': 'student-plain'})()
    legacy_teacher = type('Row', (), {'_api_key': 'teacher-plain'})()
    legacy_image = type('Row', (), {'_api_key': 'image-plain'})()

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    monkeypatch.setattr(models, 'AIConfig', type('AdminModel', (), {'query': Query([legacy_admin])}))
    monkeypatch.setattr(models, 'StudentAIConfig', type('StudentModel', (), {'query': Query([legacy_student])}))
    monkeypatch.setattr(models, 'TeacherAIConfig', type('TeacherModel', (), {'query': Query([legacy_teacher])}))
    monkeypatch.setattr(models, 'AIImageConfig', type('ImageModel', (), {'query': Query([legacy_image])}))
    commits = []
    monkeypatch.setattr(models.db.session, 'commit', lambda: commits.append(True))

    assert models.migrate_ai_credentials() == 4
    assert is_encrypted_secret(legacy_admin._api_key)
    assert is_encrypted_secret(legacy_student._api_key)
    assert is_encrypted_secret(legacy_teacher._api_key)
    assert is_encrypted_secret(legacy_image._api_key)
    assert commits == [True]
