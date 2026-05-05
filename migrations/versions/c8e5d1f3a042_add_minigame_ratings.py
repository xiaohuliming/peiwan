"""add minigame ratings

Revision ID: c8e5d1f3a042
Revises: b7c4d8e9f012
Create Date: 2026-05-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8e5d1f3a042'
down_revision = 'b7c4d8e9f012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mini_game_ratings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('game', sa.String(length=40), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False, server_default='1000'),
        sa.Column('peak_rating', sa.Integer(), nullable=False, server_default='1000'),
        sa.Column('win_streak', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('games_played', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'game', name='uq_minigame_rating_user_game'),
    )
    with op.batch_alter_table('mini_game_ratings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mini_game_ratings_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mini_game_ratings_game'), ['game'], unique=False)


def downgrade():
    with op.batch_alter_table('mini_game_ratings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mini_game_ratings_game'))
        batch_op.drop_index(batch_op.f('ix_mini_game_ratings_user_id'))
    op.drop_table('mini_game_ratings')
