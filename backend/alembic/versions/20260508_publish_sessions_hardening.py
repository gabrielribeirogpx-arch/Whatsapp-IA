"""publish and flow session hardening

Revision ID: 20260508_publish_sessions_hardening
Revises: 7c3d9a1b2f44
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260508_publish_sessions_hardening'
down_revision = '7c3d9a1b2f44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('flow_versions', sa.Column('graph_checksum', sa.String(length=64), nullable=True))
    op.add_column('flow_versions', sa.Column('start_node_id', sa.String(), nullable=True))
    op.add_column('flow_versions', sa.Column('start_text_preview', sa.String(length=255), nullable=True))
    op.add_column('flow_versions', sa.Column('created_from_source', sa.String(length=64), nullable=True))
    op.create_index('ix_flow_versions_graph_checksum', 'flow_versions', ['graph_checksum'], unique=False)

    op.execute('''
        UPDATE flow_sessions fs
        SET flow_version_id = f.published_version_id
        FROM flows f
        WHERE fs.flow_id = f.id AND fs.flow_version_id IS NULL AND f.published_version_id IS NOT NULL
    ''')
    op.alter_column('flow_sessions', 'flow_version_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)


def downgrade() -> None:
    op.alter_column('flow_sessions', 'flow_version_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.drop_index('ix_flow_versions_graph_checksum', table_name='flow_versions')
    op.drop_column('flow_versions', 'created_from_source')
    op.drop_column('flow_versions', 'start_text_preview')
    op.drop_column('flow_versions', 'start_node_id')
    op.drop_column('flow_versions', 'graph_checksum')
