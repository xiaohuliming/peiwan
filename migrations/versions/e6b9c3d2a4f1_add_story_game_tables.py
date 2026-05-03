"""add story game tables

Revision ID: e6b9c3d2a4f1
Revises: d4f8b6a1c2e3
Create Date: 2026-05-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6b9c3d2a4f1'
down_revision = 'd4f8b6a1c2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'story_player_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kook_username', sa.String(length=100), nullable=True),
        sa.Column('story_world', sa.String(length=50), nullable=False),
        sa.Column('background', sa.String(length=50), nullable=False),
        sa.Column('chapter', sa.Integer(), nullable=False),
        sa.Column('current_scene', sa.String(length=120), nullable=False),
        sa.Column('status_label', sa.String(length=120), nullable=True),
        sa.Column('last_npc', sa.String(length=50), nullable=True),
        sa.Column('flags', sa.Text(), nullable=True),
        sa.Column('traits', sa.Text(), nullable=True),
        sa.Column('current_choices', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kook_id'),
    )
    with op.batch_alter_table('story_player_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_player_states_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_player_states_user_id'), ['user_id'], unique=False)

    op.create_table(
        'story_character_relations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('character_id', sa.String(length=50), nullable=False),
        sa.Column('character_name', sa.String(length=50), nullable=False),
        sa.Column('trust', sa.Integer(), nullable=False),
        sa.Column('bond_level', sa.Integer(), nullable=False),
        sa.Column('relationship_status', sa.String(length=160), nullable=True),
        sa.Column('triggered_events', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kook_id', 'character_id', name='uq_story_relation_kook_character'),
    )
    with op.batch_alter_table('story_character_relations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_character_relations_character_id'), ['character_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_character_relations_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_character_relations_user_id'), ['user_id'], unique=False)

    op.create_table(
        'story_memory_fragments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('memory_id', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_event', sa.String(length=120), nullable=True),
        sa.Column('unlocked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kook_id', 'memory_id', name='uq_story_memory_kook_memory'),
    )
    with op.batch_alter_table('story_memory_fragments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_memory_fragments_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_memory_fragments_memory_id'), ['memory_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_memory_fragments_user_id'), ['user_id'], unique=False)

    op.create_table(
        'story_direct_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('character_id', sa.String(length=50), nullable=False),
        sa.Column('character_name', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('reply_allowed', sa.Boolean(), nullable=False),
        sa.Column('trigger_event', sa.String(length=120), nullable=True),
        sa.Column('kook_msg_id', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('replied_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('story_direct_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_direct_messages_character_id'), ['character_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_direct_messages_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_direct_messages_user_id'), ['user_id'], unique=False)

    op.create_table(
        'story_turn_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kook_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('channel_id', sa.String(length=100), nullable=True),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('visible_text', sa.Text(), nullable=True),
        sa.Column('state_updates', sa.Text(), nullable=True),
        sa.Column('llm_used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('story_turn_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_turn_logs_kook_id'), ['kook_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_story_turn_logs_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('story_turn_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_turn_logs_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_turn_logs_kook_id'))
    op.drop_table('story_turn_logs')

    with op.batch_alter_table('story_direct_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_direct_messages_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_direct_messages_kook_id'))
        batch_op.drop_index(batch_op.f('ix_story_direct_messages_character_id'))
    op.drop_table('story_direct_messages')

    with op.batch_alter_table('story_memory_fragments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_memory_fragments_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_memory_fragments_memory_id'))
        batch_op.drop_index(batch_op.f('ix_story_memory_fragments_kook_id'))
    op.drop_table('story_memory_fragments')

    with op.batch_alter_table('story_character_relations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_character_relations_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_character_relations_kook_id'))
        batch_op.drop_index(batch_op.f('ix_story_character_relations_character_id'))
    op.drop_table('story_character_relations')

    with op.batch_alter_table('story_player_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_story_player_states_user_id'))
        batch_op.drop_index(batch_op.f('ix_story_player_states_kook_id'))
    op.drop_table('story_player_states')
