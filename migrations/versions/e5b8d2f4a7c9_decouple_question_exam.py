"""question/exam decouple: exam_question link table + nullable source exam_id

Revision ID: e5b8d2f4a7c9
Revises: c3a9e7f1d2b6
Create Date: 2026-08-25 11:00:00.000000

架构变更：试题与试卷解耦——同一题可归属 0~N 套试卷。
1) 新建 exam_question（exam_id, question_id, position，唯一约束）；
2) 存量 question.exam_id 历史归属回填（position=卷内 id 序，幂等）；
3) question.exam_id 放宽可空，降级为"创建来源卷"（溯源，不再表达归属）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5b8d2f4a7c9'
down_revision = 'c3a9e7f1d2b6'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'exam_question' not in tables:
        op.create_table(
            'exam_question',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('exam_id', sa.Integer(),
                      sa.ForeignKey('exam.id'), nullable=False, index=True),
            sa.Column('question_id', sa.Integer(),
                      sa.ForeignKey('question.id'), nullable=False, index=True),
            sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
            sa.UniqueConstraint('exam_id', 'question_id', name='uq_exam_question'),
        )
    conn = op.get_bind()
    # 历史归属回填（幂等）
    conn.execute(sa.text(
        'INSERT INTO exam_question (exam_id, question_id, position)'
        ' SELECT q.exam_id, q.id,'
        ' ROW_NUMBER() OVER (PARTITION BY q.exam_id ORDER BY q.id)'
        ' FROM question q WHERE q.exam_id IS NOT NULL'
        ' AND NOT EXISTS (SELECT 1 FROM exam_question eq'
        '   WHERE eq.exam_id = q.exam_id AND eq.question_id = q.id);'
    ))
    # exam_id 放宽可空（来源卷语义）
    conn.execute(sa.text(
        'ALTER TABLE question ALTER COLUMN exam_id DROP NOT NULL;'))


def downgrade():
    conn = op.get_bind()
    # 回写单卷归属（多卷题保留第一卷），再恢复 NOT NULL 与删表
    conn.execute(sa.text(
        'UPDATE question SET exam_id = ('
        ' SELECT eq.exam_id FROM exam_question eq'
        ' WHERE eq.question_id = question.id'
        ' ORDER BY eq.position LIMIT 1);'
    ))
    # 降级保护：纯题库题（exam_id 仍为空）在旧模型下无处归属，无条件
    # 删除会静默清空题库——非空时显式报错要求人工处理
    _n = conn.execute(sa.text(
        'SELECT COUNT(*) FROM question WHERE exam_id IS NULL')).scalar()
    if _n:
        raise RuntimeError(
            f'存在 {_n} 道纯题库题（exam_id 为空），降级将丢失它们；'
            '请先为这些题指定归属试卷或手工清理后重试')
    conn.execute(sa.text(
        'DELETE FROM question WHERE exam_id IS NULL;'))
    conn.execute(sa.text(
        'ALTER TABLE question ALTER COLUMN exam_id SET NOT NULL;'))
    op.drop_table('exam_question')