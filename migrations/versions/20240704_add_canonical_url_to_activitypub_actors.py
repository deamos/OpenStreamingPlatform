"""Add canonical_url to activitypub_actors

Revision ID: 20240704_add_canonical_url
Revises: activitypub_001
Create Date: 2024-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20240704_add_canonical_url'
down_revision = 'activitypub_001'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('activitypub_actors', sa.Column('canonical_url', sa.String(length=512), nullable=True))

def downgrade():
    op.drop_column('activitypub_actors', 'canonical_url') 