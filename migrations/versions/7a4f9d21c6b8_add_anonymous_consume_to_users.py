"""add anonymous_consume to users

Revision ID: 7a4f9d21c6b8
Revises: c2f1d9e6ab34
Create Date: 2026-03-02 13:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a4f9d21c6b8'
down_revision = 'c2f1d9e6ab34'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('anonymous_consume', sa.Boolean(), nullable=True))

    op.execute("UPDATE users SET anonymous_consume = 0 WHERE anonymous_consume IS NULL")

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('anonymous_consume', existing_type=sa.Boolean(), nullable=False)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('anonymous_consume')
