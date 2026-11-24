"""expand AI API key columns for encrypted values

Revision ID: b41c9f10a7d2
Revises: ea9ae68c0f33
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'b41c9f10a7d2'
down_revision = 'ea9ae68c0f33'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('ai_config', 'api_key', existing_type=sa.String(500), type_=sa.Text())
    op.alter_column('student_ai_config', 'api_key', existing_type=sa.String(500), type_=sa.Text())


def downgrade():
    # Fernet 密文可能超过 500 字符，降级会截断并永久破坏凭据，因此拒绝破坏性回退。
    raise RuntimeError('不能安全地把已加密 API Key 列降级为 VARCHAR(500)')
