"""add interactive lottery support

Revision ID: 6bb7f0d3a12c
Revises: 2a6f3b1c9d4e
Create Date: 2026-03-11 21:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6bb7f0d3a12c'
down_revision = '2a6f3b1c9d4e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lotteries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lottery_mode', sa.String(length=20), nullable=False, server_default='reaction'))
        batch_op.create_index(batch_op.f('ix_lotteries_lottery_mode'), ['lottery_mode'], unique=False)

    with op.batch_alter_table('lotteries', schema=None) as batch_op:
        batch_op.alter_column('lottery_mode', server_default=None)

    op.create_table(
        'lottery_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lottery_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['lottery_id'], ['lotteries.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lottery_id', 'kook_id', name='uq_lottery_participants_lottery_kook'),
    )
    with op.batch_alter_table('lottery_participants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lottery_participants_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lottery_participants_lottery_id'), ['lottery_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lottery_participants_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('lottery_participants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lottery_participants_user_id'))
        batch_op.drop_index(batch_op.f('ix_lottery_participants_lottery_id'))
        batch_op.drop_index(batch_op.f('ix_lottery_participants_kook_id'))

    op.drop_table('lottery_participants')

    with op.batch_alter_table('lotteries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lotteries_lottery_mode'))
        batch_op.drop_column('lottery_mode')
