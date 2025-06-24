"""ActivityPub tables migration

Revision ID: activitypub_001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'activitypub_001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create activitypub_actors table
    op.create_table(
        'activitypub_actors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('actor_type', sa.String(length=50), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('icon_url', sa.String(length=1024), nullable=True),
        sa.Column('header_url', sa.String(length=1024), nullable=True),
        sa.Column('inbox_url', sa.String(length=1024), nullable=True),
        sa.Column('outbox_url', sa.String(length=1024), nullable=True),
        sa.Column('followers_url', sa.String(length=1024), nullable=True),
        sa.Column('following_url', sa.String(length=1024), nullable=True),
        sa.Column('public_key_pem', sa.Text(), nullable=True),
        sa.Column('private_key_pem', sa.Text(), nullable=True),
        sa.Column('is_local', sa.Boolean(), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('channel_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['Channel.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('username')
    )

    # Create activitypub_activities table
    op.create_table(
        'activitypub_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('object_data', sa.Text(), nullable=True),
        sa.Column('target_id', sa.String(length=1024), nullable=True),
        sa.Column('to', sa.Text(), nullable=True),
        sa.Column('cc', sa.Text(), nullable=True),
        sa.Column('signature', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('delivered', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['activitypub_actors.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )

    # Create activitypub_follows table
    op.create_table(
        'activitypub_follows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('follower_id', sa.Integer(), nullable=False),
        sa.Column('following_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['follower_id'], ['activitypub_actors.id'], ),
        sa.ForeignKeyConstraint(['following_id'], ['activitypub_actors.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )

    # Create activitypub_objects table
    op.create_table(
        'activitypub_objects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=255), nullable=False),
        sa.Column('object_type', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('local_object_id', sa.Integer(), nullable=True),
        sa.Column('local_object_type', sa.String(length=50), nullable=True),
        sa.Column('object_data', sa.Text(), nullable=True),
        sa.Column('published', sa.DateTime(), nullable=True),
        sa.Column('updated', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['activitypub_actors.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )

    # Create indexes for better performance
    op.create_index(op.f('ix_activitypub_actors_username'), 'activitypub_actors', ['username'], unique=False)
    op.create_index(op.f('ix_activitypub_actors_domain'), 'activitypub_actors', ['domain'], unique=False)
    op.create_index(op.f('ix_activitypub_actors_is_local'), 'activitypub_actors', ['is_local'], unique=False)
    op.create_index(op.f('ix_activitypub_activities_actor_id'), 'activitypub_activities', ['actor_id'], unique=False)
    op.create_index(op.f('ix_activitypub_activities_created_at'), 'activitypub_activities', ['created_at'], unique=False)
    op.create_index(op.f('ix_activitypub_activities_delivered'), 'activitypub_activities', ['delivered'], unique=False)
    op.create_index(op.f('ix_activitypub_follows_follower_id'), 'activitypub_follows', ['follower_id'], unique=False)
    op.create_index(op.f('ix_activitypub_follows_following_id'), 'activitypub_follows', ['following_id'], unique=False)
    op.create_index(op.f('ix_activitypub_follows_status'), 'activitypub_follows', ['status'], unique=False)
    op.create_index(op.f('ix_activitypub_objects_actor_id'), 'activitypub_objects', ['actor_id'], unique=False)
    op.create_index(op.f('ix_activitypub_objects_local_object_id'), 'activitypub_objects', ['local_object_id'], unique=False)
    op.create_index(op.f('ix_activitypub_objects_local_object_type'), 'activitypub_objects', ['local_object_type'], unique=False)


def downgrade():
    # Drop indexes
    op.drop_index(op.f('ix_activitypub_objects_local_object_type'), table_name='activitypub_objects')
    op.drop_index(op.f('ix_activitypub_objects_local_object_id'), table_name='activitypub_objects')
    op.drop_index(op.f('ix_activitypub_objects_actor_id'), table_name='activitypub_objects')
    op.drop_index(op.f('ix_activitypub_follows_status'), table_name='activitypub_follows')
    op.drop_index(op.f('ix_activitypub_follows_following_id'), table_name='activitypub_follows')
    op.drop_index(op.f('ix_activitypub_follows_follower_id'), table_name='activitypub_follows')
    op.drop_index(op.f('ix_activitypub_activities_delivered'), table_name='activitypub_activities')
    op.drop_index(op.f('ix_activitypub_activities_created_at'), table_name='activitypub_activities')
    op.drop_index(op.f('ix_activitypub_activities_actor_id'), table_name='activitypub_activities')
    op.drop_index(op.f('ix_activitypub_actors_is_local'), table_name='activitypub_actors')
    op.drop_index(op.f('ix_activitypub_actors_domain'), table_name='activitypub_actors')
    op.drop_index(op.f('ix_activitypub_actors_username'), table_name='activitypub_actors')

    # Drop tables
    op.drop_table('activitypub_objects')
    op.drop_table('activitypub_follows')
    op.drop_table('activitypub_activities')
    op.drop_table('activitypub_actors') 