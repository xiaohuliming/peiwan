"""add price_devil tier to project_items

Revision ID: 1c9e6e84f5aa
Revises: 7a4f9d21c6b8
Create Date: 2026-03-02 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c9e6e84f5aa'
down_revision = '7a4f9d21c6b8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('price_devil', sa.Numeric(precision=10, scale=2), nullable=True))

    # 默认将魔王档初始化为旧巅峰档价格，避免升级后出现 0 价
    op.execute("UPDATE project_items SET price_devil = COALESCE(price_pro, 0) WHERE price_devil IS NULL")

    with op.batch_alter_table('project_items', schema=None) as batch_op:
        batch_op.alter_column('price_devil', existing_type=sa.Numeric(precision=10, scale=2), nullable=False)


def downgrade():
    with op.batch_alter_table('project_items', schema=None) as batch_op:
        batch_op.drop_column('price_devil')
