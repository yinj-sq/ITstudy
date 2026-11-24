"""add student_drive_file.pptist_json for personal-drive PPTist editing

Revision ID: c3a9e7f1d2b6
Revises: b7e1c9d3f5a8
Create Date: 2026-08-24 20:00:00.000000

说明：个人网盘 PPTX 接入 PPTist 编辑（与小组网盘 group_file.pptist_json
同构）：浏览器内 pptxtojson 解析结果回存该列。幂等（列已存在则跳过）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3a9e7f1d2b6'
down_revision = 'b7e1c9d3f5a8'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    has_col = 'pptist_json' in {c['name'] for c in insp.get_columns('student_drive_file')}
    if not has_col:
        op.add_column('student_drive_file', sa.Column('pptist_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('student_drive_file', 'pptist_json')
