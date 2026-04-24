"""add version_number to flow_versions

Revision ID: 3bbc2e0c6b1e
Revises: da4e2fa678e1
Create Date: 2026-04-24 20:30:54.011452

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3bbc2e0c6b1e'
down_revision = 'da4e2fa678e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'flow_versions',
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1')
    )


def downgrade():
    op.drop_column('flow_versions', 'version_number')