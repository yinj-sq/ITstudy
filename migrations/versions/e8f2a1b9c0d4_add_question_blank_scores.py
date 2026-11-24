"""add question.blank_scores for python_fill per-blank scoring

Revision ID: e8f2a1b9c0d4
Revises: d72f6a03c8e1
Create Date: 2026-08-11 22:30:00.000000

说明：Python 填空题批量导入需按空精确计分（如 3 空 3/3/4 分），
Question 表新增 blank_scores（JSON 数组）存每空分值；判分时存在则
逐空取分，否则回退均分（存量题行为不变）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8f2a1b9c0d4'
down_revision = 'd72f6a03c8e1'
branch_labels = None
depends_on = None


def upgrade():
    # 幂等：开发库中该列可能已被手工添加，存在则跳过
    insp = sa.inspect(op.get_bind())
    has_col = 'blank_scores' in {c['name'] for c in insp.get_columns('question')}
    if not has_col:
        op.add_column('question', sa.Column('blank_scores', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('question', 'blank_scores')
