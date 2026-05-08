"""publish and flow session hardening

Revision ID: 20260508_publish_sessions_hardening
Revises: 7c3d9a1b2f44
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

revision = '20260508_pub_sess_hard'
down_revision = '7c3d9a1b2f44'
branch_labels = None
depends_on = None


FLOW_VERSION_FK_NAME = 'fk_flow_sessions_flow_version_id_flow_versions'
FLOW_VERSION_INDEX = 'ix_flow_versions_graph_checksum'


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {c['name'] for c in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {i['name'] for i in inspector.get_indexes(table_name)}


def _has_fk(inspector, table_name: str, fk_name: str) -> bool:
    return fk_name in {fk['name'] for fk in inspector.get_foreign_keys(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) Add flow_versions columns first.
    if not _has_column(inspector, 'flow_versions', 'graph_checksum'):
        op.add_column('flow_versions', sa.Column('graph_checksum', sa.String(length=64), nullable=True))
    if not _has_column(inspector, 'flow_versions', 'start_node_id'):
        op.add_column('flow_versions', sa.Column('start_node_id', sa.String(), nullable=True))
    if not _has_column(inspector, 'flow_versions', 'start_text_preview'):
        op.add_column('flow_versions', sa.Column('start_text_preview', sa.String(length=255), nullable=True))
    if not _has_column(inspector, 'flow_versions', 'created_from_source'):
        op.add_column('flow_versions', sa.Column('created_from_source', sa.String(length=64), nullable=True))

    inspector = inspect(bind)
    if not _has_index(inspector, 'flow_versions', FLOW_VERSION_INDEX):
        op.create_index(FLOW_VERSION_INDEX, 'flow_versions', ['graph_checksum'], unique=False)

    # 2) Ensure flow_sessions.flow_version_id exists and is nullable before backfill.
    if not _has_column(inspector, 'flow_sessions', 'flow_version_id'):
        op.add_column('flow_sessions', sa.Column('flow_version_id', postgresql.UUID(as_uuid=True), nullable=True))
        inspector = inspect(bind)

    # 3) Backfill flow_version_id.
    op.execute(
        text(
            '''
            UPDATE flow_sessions fs
            SET flow_version_id = f.published_version_id
            FROM flows f
            WHERE fs.flow_id = f.id
              AND fs.flow_version_id IS NULL
              AND f.published_version_id IS NOT NULL
            '''
        )
    )

    # 4) Safe cleanup for terminal sessions still NULL.
    op.execute(
        text(
            """
            DELETE FROM flow_sessions
            WHERE flow_version_id IS NULL
              AND status IN ('finished', 'expired', 'cancelled')
            """
        )
    )

    # 5) Create FK only after backfill/cleanup.
    inspector = inspect(bind)
    if not _has_fk(inspector, 'flow_sessions', FLOW_VERSION_FK_NAME):
        op.create_foreign_key(
            FLOW_VERSION_FK_NAME,
            'flow_sessions',
            'flow_versions',
            ['flow_version_id'],
            ['id'],
            ondelete='RESTRICT',
        )

    # 6) Enforce NOT NULL only when safe.
    null_count = bind.execute(text('SELECT COUNT(*) FROM flow_sessions WHERE flow_version_id IS NULL')).scalar_one()
    if null_count == 0:
        op.alter_column(
            'flow_sessions',
            'flow_version_id',
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, 'flow_sessions', 'flow_version_id'):
        op.alter_column('flow_sessions', 'flow_version_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    if _has_fk(inspector, 'flow_sessions', FLOW_VERSION_FK_NAME):
        op.drop_constraint(FLOW_VERSION_FK_NAME, 'flow_sessions', type_='foreignkey')

    if _has_index(inspector, 'flow_versions', FLOW_VERSION_INDEX):
        op.drop_index(FLOW_VERSION_INDEX, table_name='flow_versions')

    if _has_column(inspector, 'flow_versions', 'created_from_source'):
        op.drop_column('flow_versions', 'created_from_source')
    if _has_column(inspector, 'flow_versions', 'start_text_preview'):
        op.drop_column('flow_versions', 'start_text_preview')
    if _has_column(inspector, 'flow_versions', 'start_node_id'):
        op.drop_column('flow_versions', 'start_node_id')
    if _has_column(inspector, 'flow_versions', 'graph_checksum'):
        op.drop_column('flow_versions', 'graph_checksum')
