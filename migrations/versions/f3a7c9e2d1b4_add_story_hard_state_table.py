"""add story hard state table

Revision ID: f3a7c9e2d1b4
Revises: e6b9c3d2a4f1
Create Date: 2026-05-03 23:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a7c9e2d1b4'
down_revision = 'e6b9c3d2a4f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'story_hard_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('location_id', sa.String(length=120), nullable=False),
        sa.Column('location_name', sa.String(length=120), nullable=False),
        sa.Column('mission_id', sa.String(length=120), nullable=False),
        sa.Column('mission_name', sa.String(length=120), nullable=False),
        sa.Column('mission_status', sa.String(length=50), nullable=False),
        sa.Column('mission_progress', sa.Integer(), nullable=False),
        sa.Column('inventory', sa.Text(), nullable=True),
        sa.Column('npc_states', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kook_id'),
    )
    with op.batch_alter_table('story_hard_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_hard_states_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_hard_states_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('story_hard_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_hard_states_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_hard_states_kook_id'))
    op.drop_table('story_hard_states')
