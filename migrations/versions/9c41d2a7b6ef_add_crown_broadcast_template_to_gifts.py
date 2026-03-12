"""add crown broadcast template to gifts

Revision ID: 9c41d2a7b6ef
Revises: 6bb7f0d3a12c
Create Date: 2026-03-12 10:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c41d2a7b6ef'
down_revision = '6bb7f0d3a12c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('gifts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('crown_broadcast_template', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('gifts', schema=None) as batch_op:
        batch_op.drop_column('crown_broadcast_template')
