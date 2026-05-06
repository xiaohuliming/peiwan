"""add voice (idle) stats tables

Revision ID: e9d1f4a72b56
Revises: c8e5d1f3a042
Create Date: 2026-05-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e9d1f4a72b56'
down_revision = 'c8e5d1f3a042'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'voice_stat_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('min_session_seconds', sa.Integer(), nullable=False),
        sa.Column('truncate_hours', sa.Integer(), nullable=False),
        sa.Column('whitelist_channel_ids', sa.Text(), nullable=True),
        sa.Column('blacklist_channel_ids', sa.Text(), nullable=True),
        sa.Column('whitelist_kook_ids', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'voice_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('channel_id', sa.String(length=100), nullable=False),
        sa.Column('channel_name', sa.String(length=120), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.Column('left_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=True),
        sa.Column('note', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('voice_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_voice_sessions_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_sessions_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_sessions_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_sessions_joined_at'), ['joined_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_sessions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_sessions_stat_date'), ['stat_date'], unique=False)

    op.create_table(
        'voice_daily_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=False),
        sa.Column('channel_id', sa.String(length=100), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('sessions_count', sa.Integer(), nullable=False),
        sa.Column('total_seconds', sa.Integer(), nullable=False),
        sa.Column('last_left_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', 'channel_id', 'kook_id', name='uq_voice_daily_user_channel'),
    )
    with op.batch_alter_table('voice_daily_stats', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_voice_daily_stats_stat_date'), ['stat_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_daily_stats_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_daily_stats_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_voice_daily_stats_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('voice_daily_stats', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_voice_daily_stats_user_id'))
        batch_op.drop_index(batch_op.f('ix_voice_daily_stats_kook_id'))
        batch_op.drop_index(batch_op.f('ix_voice_daily_stats_channel_id'))
        batch_op.drop_index(batch_op.f('ix_voice_daily_stats_stat_date'))
    op.drop_table('voice_daily_stats')

    with op.batch_alter_table('voice_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_voice_sessions_stat_date'))
        batch_op.drop_index(batch_op.f('ix_voice_sessions_status'))
        batch_op.drop_index(batch_op.f('ix_voice_sessions_joined_at'))
        batch_op.drop_index(batch_op.f('ix_voice_sessions_channel_id'))
        batch_op.drop_index(batch_op.f('ix_voice_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_voice_sessions_kook_id'))
    op.drop_table('voice_sessions')

    op.drop_table('voice_stat_configs')
