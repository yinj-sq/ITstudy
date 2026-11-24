"""资源测验逐题快照（兼容启动时的幂等自动补列）。"""
from alembic import op
import sqlalchemy as sa

revision = 'f3c8b1d9a210'
down_revision = 'e5b8d2f4a7c9'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in
               sa.inspect(op.get_bind()).get_columns('resource_quiz_result')}
    if 'question_details' not in columns:
        op.add_column('resource_quiz_result', sa.Column('question_details', sa.Text(), nullable=True))


def downgrade():
    columns = {column['name'] for column in
               sa.inspect(op.get_bind()).get_columns('resource_quiz_result')}
    if 'question_details' in columns:
        op.drop_column('resource_quiz_result', 'question_details')
