"""Initial schema

Revision ID: c7b49c514c84
Revises:
Create Date: 2026-05-19 10:00:36.591815

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c7b49c514c84'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """通过 SQLAlchemy metadata 创建所有表 + 索引，幂等执行"""
    from flask import current_app
    db = current_app.extensions['migrate'].db
    db.create_all()
    # 补充 IF NOT EXISTS 索引（db.create_all 不保证创建 auto-generated 索引名之外的索引）
    op.execute('CREATE INDEX IF NOT EXISTS idx_class_name ON classes (name)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_exam_is_active ON exam (is_active)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_log_time ON log (time)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_python_answer_question_id ON python_answer (question_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_python_answer_student_id ON python_answer (student_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_question_exam_id ON question (exam_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_result_exam_id ON result (exam_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_result_student_id ON result (student_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_schedule_sort ON schedule (sort_order)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_student_class ON student (student_class)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_student_class_id ON student (class_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_student_group_id ON student (group_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_student_name ON student (name)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_student_number ON student (student_number)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_study_group_class_id ON study_group (class_id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_subquestion_question_id ON sub_question (question_id)')


def downgrade():
    """删除所有索引"""
    op.execute('DROP INDEX IF EXISTS idx_subquestion_question_id')
    op.execute('DROP INDEX IF EXISTS idx_study_group_class_id')
    op.execute('DROP INDEX IF EXISTS idx_student_number')
    op.execute('DROP INDEX IF EXISTS idx_student_name')
    op.execute('DROP INDEX IF EXISTS idx_student_group_id')
    op.execute('DROP INDEX IF EXISTS idx_student_class_id')
    op.execute('DROP INDEX IF EXISTS idx_student_class')
    op.execute('DROP INDEX IF EXISTS idx_schedule_sort')
    op.execute('DROP INDEX IF EXISTS idx_result_student_id')
    op.execute('DROP INDEX IF EXISTS idx_result_exam_id')
    op.execute('DROP INDEX IF EXISTS idx_question_exam_id')
    op.execute('DROP INDEX IF EXISTS idx_python_answer_student_id')
    op.execute('DROP INDEX IF EXISTS idx_python_answer_question_id')
    op.execute('DROP INDEX IF EXISTS idx_log_time')
    op.execute('DROP INDEX IF EXISTS idx_exam_is_active')
    op.execute('DROP INDEX IF EXISTS idx_class_name')
