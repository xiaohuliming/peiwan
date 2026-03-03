"""add sort_order to gifts

Revision ID: 3f6c4a9d1b2e
Revises: 1c9e6e84f5aa
Create Date: 2026-03-03 02:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f6c4a9d1b2e'
down_revision = '1c9e6e84f5aa'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('gifts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_index(batch_op.f('ix_gifts_sort_order'), ['sort_order'], unique=False)

    # 回填历史数据：默认按 id 顺序
    op.execute(sa.text('UPDATE gifts SET sort_order = id WHERE sort_order = 0 OR sort_order IS NULL'))

    with op.batch_alter_table('gifts', schema=None) as batch_op:
        batch_op.alter_column('sort_order', server_default=None)


def downgrade():
    with op.batch_alter_table('gifts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_gifts_sort_order'))
        batch_op.drop_column('sort_order')

