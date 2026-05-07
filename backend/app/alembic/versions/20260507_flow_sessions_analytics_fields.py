"""add analytics fields to flow_sessions

Revision ID: 20260507_flow_sessions_analytics
Revises: 20260505_tenant_perf_idempotency
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260507_flow_sessions_analytics"
down_revision = "20260505_tenant_perf_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flow_sessions", sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("flow_sessions", sa.Column("started_at", sa.DateTime(), nullable=True, server_default=sa.text("now()")))
    op.add_column("flow_sessions", sa.Column("ended_at", sa.DateTime(), nullable=True))
    op.add_column("flow_sessions", sa.Column("last_event_at", sa.DateTime(), nullable=True, server_default=sa.text("now()")))
    op.add_column("flow_sessions", sa.Column("completion_status", sa.String(), nullable=True, server_default="running"))
    op.add_column("flow_sessions", sa.Column("conversion_at", sa.DateTime(), nullable=True))
    op.add_column("flow_sessions", sa.Column("abandon_reason", sa.String(), nullable=True))

    op.create_foreign_key(
        "fk_flow_sessions_flow_version_id_flow_versions",
        "flow_sessions",
        "flow_versions",
        ["flow_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_flow_sessions_last_event_at", "flow_sessions", ["last_event_at"], unique=False)
    op.create_index(
        "ix_flow_sessions_tenant_flow_started_at",
        "flow_sessions",
        ["tenant_id", "flow_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_flow_sessions_tenant_flow_completion_started_at",
        "flow_sessions",
        ["tenant_id", "flow_id", "completion_status", "started_at"],
        unique=False,
    )

    op.execute("UPDATE flow_sessions SET completion_status = COALESCE(status, 'running') WHERE completion_status IS NULL")
    op.execute("UPDATE flow_sessions SET started_at = COALESCE(created_at, now()) WHERE started_at IS NULL")
    op.execute("UPDATE flow_sessions SET last_event_at = COALESCE(updated_at, created_at, now()) WHERE last_event_at IS NULL")


def downgrade() -> None:
    op.drop_index("ix_flow_sessions_tenant_flow_completion_started_at", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_tenant_flow_started_at", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_last_event_at", table_name="flow_sessions")
    op.drop_constraint("fk_flow_sessions_flow_version_id_flow_versions", "flow_sessions", type_="foreignkey")
    op.drop_column("flow_sessions", "abandon_reason")
    op.drop_column("flow_sessions", "conversion_at")
    op.drop_column("flow_sessions", "completion_status")
    op.drop_column("flow_sessions", "last_event_at")
    op.drop_column("flow_sessions", "ended_at")
    op.drop_column("flow_sessions", "started_at")
    op.drop_column("flow_sessions", "flow_version_id")
