"""add performance composite indexes (no-op: indexes already created)

Revision ID: ea9ae68c0f33
Revises: c7b49c514c84
Create Date: 2026-06-02 11:18:36.200104

说明：原本计划添加的复合索引（ix_result_student_exam、ix_result_exam_submit、
ix_log_time_user 等）已经在初始迁移 c7b49c514c84 的 db.create_all() 中通过
模型 __table_args__ 自动创建。本迁移保留为占位记录以保持迁移历史一致。
"""


# revision identifiers, used by Alembic.
revision = 'ea9ae68c0f33'
down_revision = 'c7b49c514c84'
branch_labels = None
depends_on = None


def upgrade():
    # 索引已在初始迁移中创建，此处无需重复操作
    pass


def downgrade():
    # 索引已由模型维护，downgrade 不做破坏性删除
    pass
