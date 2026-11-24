"""add exam.name unique constraint

Revision ID: b7e1c9d3f5a8
Revises: e8f2a1b9c0d4
Create Date: 2026-08-14 20:00:00.000000

说明：试卷名全局唯一（应用层四处查重 + 批量导入按卷名避让依赖此约定）。
存量重名先自动追加「（id）」后缀改名（保留数据），再建唯一约束；
幂等（约束已存在时跳过）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e1c9d3f5a8'
down_revision = 'e8f2a1b9c0d4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # 存量重名改名（幂等：改名后不再存在 rn>1 的行）。
    # LEFT(name,90) 截断防拼接后超出 VARCHAR(100) 导致迁移中断
    conn.execute(sa.text(
        "UPDATE exam SET name = LEFT(name, 90) || '（' || id || '）'"
        " WHERE id IN (SELECT id FROM (SELECT id,"
        " ROW_NUMBER() OVER (PARTITION BY name ORDER BY id) AS rn"
        " FROM exam) t WHERE rn > 1);"
    ))
    # 幂等建唯一约束（migrate_db 的运行时迁移可能已建）
    conn.execute(sa.text(
        "DO $$ BEGIN"
        " IF NOT EXISTS (SELECT 1 FROM pg_constraint"
        "                WHERE conname = 'uq_exam_name') THEN"
        "  ALTER TABLE exam ADD CONSTRAINT uq_exam_name UNIQUE (name);"
        " END IF;"
        " END $$;"
    ))


def downgrade():
    op.drop_constraint('uq_exam_name', 'exam', type_='unique')
