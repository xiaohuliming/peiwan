"""add chat stats bot tables

Revision ID: d4f8b6a1c2e3
Revises: a7d3c2f1e4b9
Create Date: 2026-05-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4f8b6a1c2e3'
down_revision = 'a7d3c2f1e4b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'chat_stat_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('channel_ids', sa.Text(), nullable=True),
        sa.Column('whitelist_kook_ids', sa.Text(), nullable=True),
        sa.Column('duplicate_limit', sa.Integer(), nullable=False),
        sa.Column('rank_limit', sa.Integer(), nullable=False),
        sa.Column('daily_title', sa.String(length=80), nullable=False),
        sa.Column('weekly_title', sa.String(length=80), nullable=False),
        sa.Column('daily_broadcast_channel_id', sa.String(length=100), nullable=True),
        sa.Column('weekly_broadcast_channel_id', sa.String(length=100), nullable=True),
        sa.Column('checkin_broadcast_channel_id', sa.String(length=100), nullable=True),
        sa.Column('rank_broadcast_enabled', sa.Boolean(), nullable=False),
        sa.Column('checkin_broadcast_enabled', sa.Boolean(), nullable=False),
        sa.Column('milestone_rewards', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'chat_bot_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('display_name', sa.String(length=120), nullable=True),
        sa.Column('title', sa.String(length=80), nullable=True),
        sa.Column('badge', sa.String(length=80), nullable=True),
        sa.Column('sign_in_streak', sa.Integer(), nullable=False),
        sa.Column('total_checkins', sa.Integer(), nullable=False),
        sa.Column('last_checkin_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kook_id'),
    )
    with op.batch_alter_table('chat_bot_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_bot_profiles_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_bot_profiles_user_id'), ['user_id'], unique=False)

    op.create_table(
        'chat_daily_user_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=False),
        sa.Column('channel_id', sa.String(length=100), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('total_count', sa.Integer(), nullable=False),
        sa.Column('valid_count', sa.Integer(), nullable=False),
        sa.Column('filtered_count', sa.Integer(), nullable=False),
        sa.Column('duplicate_filtered_count', sa.Integer(), nullable=False),
        sa.Column('meaningless_filtered_count', sa.Integer(), nullable=False),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', 'channel_id', 'kook_id', name='uq_chat_daily_user_channel'),
    )
    with op.batch_alter_table('chat_daily_user_stats', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_daily_user_stats_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_user_stats_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_user_stats_stat_date'), ['stat_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_user_stats_user_id'), ['user_id'], unique=False)

    op.create_table(
        'chat_daily_content_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stat_date', sa.Date(), nullable=False),
        sa.Column('channel_id', sa.String(length=100), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('content_sample', sa.String(length=200), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stat_date', 'channel_id', 'kook_id', 'content_hash', name='uq_chat_daily_content'),
    )
    with op.batch_alter_table('chat_daily_content_stats', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_daily_content_stats_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_content_stats_content_hash'), ['content_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_content_stats_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_daily_content_stats_stat_date'), ['stat_date'], unique=False)

    op.create_table(
        'chat_rank_settlements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('period_type', sa.String(length=20), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('rank_no', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('valid_count', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=80), nullable=True),
        sa.Column('badge', sa.String(length=80), nullable=True),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('period_type', 'period_start', 'period_end', 'rank_no', name='uq_chat_rank_period_rank'),
    )
    with op.batch_alter_table('chat_rank_settlements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_rank_settlements_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_rank_settlements_period_end'), ['period_end'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_rank_settlements_period_start'), ['period_start'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_rank_settlements_period_type'), ['period_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_rank_settlements_user_id'), ['user_id'], unique=False)

    op.create_table(
        'chat_checkin_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('checkin_date', sa.Date(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('channel_id', sa.String(length=100), nullable=True),
        sa.Column('streak_after', sa.Integer(), nullable=False),
        sa.Column('total_after', sa.Integer(), nullable=False),
        sa.Column('reward_title', sa.String(length=80), nullable=True),
        sa.Column('reward_badge', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('checkin_date', 'kook_id', name='uq_chat_checkin_date_kook'),
    )
    with op.batch_alter_table('chat_checkin_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_checkin_records_checkin_date'), ['checkin_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_checkin_records_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chat_checkin_records_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('chat_checkin_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_checkin_records_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_checkin_records_kook_id'))
        batch_op.drop_index(batch_op.f('ix_chat_checkin_records_checkin_date'))
    op.drop_table('chat_checkin_records')

    with op.batch_alter_table('chat_rank_settlements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_rank_settlements_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_rank_settlements_period_type'))
        batch_op.drop_index(batch_op.f('ix_chat_rank_settlements_period_start'))
        batch_op.drop_index(batch_op.f('ix_chat_rank_settlements_period_end'))
        batch_op.drop_index(batch_op.f('ix_chat_rank_settlements_kook_id'))
    op.drop_table('chat_rank_settlements')

    with op.batch_alter_table('chat_daily_content_stats', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_daily_content_stats_stat_date'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_content_stats_kook_id'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_content_stats_content_hash'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_content_stats_channel_id'))
    op.drop_table('chat_daily_content_stats')

    with op.batch_alter_table('chat_daily_user_stats', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_daily_user_stats_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_user_stats_stat_date'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_user_stats_kook_id'))
        batch_op.drop_index(batch_op.f('ix_chat_daily_user_stats_channel_id'))
    op.drop_table('chat_daily_user_stats')

    with op.batch_alter_table('chat_bot_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_bot_profiles_user_id'))
        batch_op.drop_index(batch_op.f('ix_chat_bot_profiles_kook_id'))
    op.drop_table('chat_bot_profiles')

    op.drop_table('chat_stat_configs')
