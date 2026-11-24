"""drop legacy plaintext student password column

Revision ID: d72f6a03c8e1
Revises: b41c9f10a7d2
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'd72f6a03c8e1'
down_revision = 'b41c9f10a7d2'
branch_labels = None
depends_on = None


def upgrade():
    """幂等删除遗留的明文密码列：仅当列存在时删除。

    历史库（旧模型含 plain_password）需要清理该列；而新部署由
    c7b49c514c84 的 db.create_all() 基于当前模型建表，student 表
    根本没有该列——无条件 DROP COLUMN 会抛 UndefinedColumn 并中断
    整个迁移链（事务回滚）。故先检查 information_schema 再删除。
    """
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'student' AND column_name = 'plain_password'"
        " LIMIT 1"
    )).first()
    if exists:
        op.drop_column('student', 'plain_password')


def downgrade():
    # 仅恢复空列，不可能恢复已经安全删除的明文密码。
    op.add_column('student', sa.Column('plain_password', sa.String(50), nullable=True))
