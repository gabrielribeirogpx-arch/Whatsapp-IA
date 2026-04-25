"""ensure flow_versions.version column exists

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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('flow_versions')}

    if 'version' not in columns and 'version_number' in columns:
        op.alter_column('flow_versions', 'version_number', new_column_name='version')
    elif 'version' not in columns:
        op.add_column(
            'flow_versions',
            sa.Column('version', sa.Integer(), nullable=False, server_default='1')
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('flow_versions')}

    if 'version' in columns and 'version_number' not in columns:
        op.alter_column('flow_versions', 'version', new_column_name='version_number')
    elif 'version' in columns:
        op.drop_column('flow_versions', 'version')