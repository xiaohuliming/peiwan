"""add target level to broadcast configs

Revision ID: a7d3c2f1e4b9
Revises: 9c41d2a7b6ef
Create Date: 2026-03-13 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'a7d3c2f1e4b9'
down_revision = '9c41d2a7b6ef'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('broadcast_configs')}
    if 'target_level' not in columns:
        with op.batch_alter_table('broadcast_configs', schema=None) as batch_op:
            batch_op.add_column(sa.Column('target_level', sa.String(length=50), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('broadcast_configs')}
    if 'target_level' in columns:
        with op.batch_alter_table('broadcast_configs', schema=None) as batch_op:
            batch_op.drop_column('target_level')
