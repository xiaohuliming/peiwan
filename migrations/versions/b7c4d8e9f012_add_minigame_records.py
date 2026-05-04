"""add minigame records

Revision ID: b7c4d8e9f012
Revises: f3a7c9e2d1b4
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c4d8e9f012'
down_revision = 'f3a7c9e2d1b4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mini_game_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game', sa.String(length=40), nullable=False),
        sa.Column('game_label', sa.String(length=40), nullable=False),
        sa.Column('channel_id', sa.String(length=100), nullable=True),
        sa.Column('player1_kook_id', sa.String(length=50), nullable=True),
        sa.Column('player1_user_id', sa.Integer(), nullable=True),
        sa.Column('player1_name', sa.String(length=120), nullable=True),
        sa.Column('player2_kook_id', sa.String(length=50), nullable=True),
        sa.Column('player2_user_id', sa.Integer(), nullable=True),
        sa.Column('player2_name', sa.String(length=120), nullable=True),
        sa.Column('winner_kook_id', sa.String(length=50), nullable=True),
        sa.Column('winner_user_id', sa.Integer(), nullable=True),
        sa.Column('winner_name', sa.String(length=120), nullable=True),
        sa.Column('result', sa.String(length=20), nullable=False),
        sa.Column('end_reason', sa.String(length=50), nullable=True),
        sa.Column('abandoned_by_kook_id', sa.String(length=50), nullable=True),
        sa.Column('moves', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['player1_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['player2_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['winner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('mini_game_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mini_game_records_abandoned_by_kook_id'), ['abandoned_by_kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_ended_at'), ['ended_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_game'), ['game'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_player1_kook_id'), ['player1_kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_player1_user_id'), ['player1_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_player2_kook_id'), ['player2_kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_player2_user_id'), ['player2_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_result'), ['result'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_winner_kook_id'), ['winner_kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_records_winner_user_id'), ['winner_user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('mini_game_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mini_game_records_winner_user_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_winner_kook_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_result'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_player2_user_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_player2_kook_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_player1_user_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_player1_kook_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_game'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_ended_at'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_channel_id'))
        batch_op.drop_index(batch_op.f('ix_mini_game_records_abandoned_by_kook_id'))
    op.drop_table('mini_game_records')
