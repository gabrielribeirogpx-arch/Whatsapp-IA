"""flow runtime v2 core

Revision ID: 20260603_flow_v2_core
Revises: 20260601_release_hidden_phone
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

revision = "20260603_flow_v2_core"
down_revision = "20260601_release_hidden_phone"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return _has_table(inspector, table_name) and column_name in {c["name"] for c in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return _has_table(inspector, table_name) and index_name in {i["name"] for i in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, "flow_versions", "v2_snapshot_hash"):
        op.add_column("flow_versions", sa.Column("v2_snapshot_hash", sa.String(length=64), nullable=True))
    if not _has_column(inspector, "flow_versions", "v2_snapshot_schema_version"):
        op.add_column("flow_versions", sa.Column("v2_snapshot_schema_version", sa.Integer(), nullable=True))

    inspector = inspect(bind)
    if not _has_index(inspector, "flow_versions", "ix_flow_versions_v2_snapshot_hash"):
        op.create_index("ix_flow_versions_v2_snapshot_hash", "flow_versions", ["v2_snapshot_hash"], unique=False)

    if not _has_table(inspector, "flow_v2_sessions"):
        op.create_table(
            "flow_v2_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("external_user_id", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
            sa.Column("current_node_id", sa.String(length=128), nullable=True),
            sa.Column("last_event_index", sa.Integer(), server_default="0", nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.ForeignKeyConstraint(["flow_version_id"], ["flow_versions.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    session_indexes = {
        "ix_flow_v2_sessions_tenant_id": ["tenant_id"],
        "ix_flow_v2_sessions_flow_version_id": ["flow_version_id"],
        "ix_flow_v2_sessions_contact_id": ["contact_id"],
        "ix_flow_v2_sessions_conversation_id": ["conversation_id"],
        "ix_flow_v2_sessions_external_user_id": ["external_user_id"],
        "ix_flow_v2_sessions_status": ["status"],
        "ix_flow_v2_sessions_started_at": ["started_at"],
    }
    for index_name, columns in session_indexes.items():
        if not _has_index(inspector, "flow_v2_sessions", index_name):
            op.create_index(index_name, "flow_v2_sessions", columns, unique=False)

    if not _has_index(inspector, "flow_v2_sessions", "uq_flow_v2_active_session_identity"):
        op.create_index(
            "uq_flow_v2_active_session_identity",
            "flow_v2_sessions",
            ["tenant_id", "flow_version_id", "external_user_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('running', 'waiting')"),
        )

    if not _has_table(inspector, "flow_v2_events"):
        op.create_table(
            "flow_v2_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_index", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("node_id", sa.String(length=128), nullable=True),
            sa.Column("input_message_id", sa.String(length=180), nullable=True),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["flow_version_id"], ["flow_versions.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["session_id"], ["flow_v2_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", "event_index", name="uq_flow_v2_events_session_index"),
            sa.UniqueConstraint("tenant_id", "input_message_id", "event_type", name="uq_flow_v2_events_input_idempotency"),
        )

    inspector = inspect(bind)
    event_indexes = {
        "ix_flow_v2_events_tenant_id": ["tenant_id"],
        "ix_flow_v2_events_session_id": ["session_id"],
        "ix_flow_v2_events_flow_version_id": ["flow_version_id"],
        "ix_flow_v2_events_event_type": ["event_type"],
        "ix_flow_v2_events_node_id": ["node_id"],
        "ix_flow_v2_events_input_message_id": ["input_message_id"],
        "ix_flow_v2_events_created_at": ["created_at"],
    }
    for index_name, columns in event_indexes.items():
        if not _has_index(inspector, "flow_v2_events", index_name):
            op.create_index(index_name, "flow_v2_events", columns, unique=False)

    inspector = inspect(bind)
    if not _has_table(inspector, "flow_v2_scheduled_jobs"):
        op.create_table(
            "flow_v2_scheduled_jobs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("resume_node_id", sa.String(length=128), nullable=False),
            sa.Column("run_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["flow_v2_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    scheduled_job_indexes = {
        "ix_flow_v2_scheduled_jobs_tenant_id": ["tenant_id"],
        "ix_flow_v2_scheduled_jobs_session_id": ["session_id"],
        "ix_flow_v2_scheduled_jobs_resume_node_id": ["resume_node_id"],
        "ix_flow_v2_scheduled_jobs_run_at": ["run_at"],
        "ix_flow_v2_scheduled_jobs_created_at": ["created_at"],
    }
    for index_name, columns in scheduled_job_indexes.items():
        if not _has_index(inspector, "flow_v2_scheduled_jobs", index_name):
            op.create_index(index_name, "flow_v2_scheduled_jobs", columns, unique=False)

    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION prevent_flow_v2_snapshot_mutation()
            RETURNS trigger AS $$
            BEGIN
              IF OLD.v2_snapshot_hash IS NOT NULL AND (
                   OLD.snapshot IS DISTINCT FROM NEW.snapshot OR
                   OLD.v2_snapshot_hash IS DISTINCT FROM NEW.v2_snapshot_hash OR
                   OLD.v2_snapshot_schema_version IS DISTINCT FROM NEW.v2_snapshot_schema_version
                 ) THEN
                RAISE EXCEPTION 'flow_versions V2 snapshot is immutable once v2_snapshot_hash is set';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_prevent_flow_v2_snapshot_mutation ON flow_versions;
            CREATE TRIGGER trg_prevent_flow_v2_snapshot_mutation
            BEFORE UPDATE ON flow_versions
            FOR EACH ROW
            EXECUTE FUNCTION prevent_flow_v2_snapshot_mutation();
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    op.execute("DROP TRIGGER IF EXISTS trg_prevent_flow_v2_snapshot_mutation ON flow_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_flow_v2_snapshot_mutation()")

    if _has_table(inspector, "flow_v2_scheduled_jobs"):
        op.drop_table("flow_v2_scheduled_jobs")
    inspector = inspect(bind)
    if _has_table(inspector, "flow_v2_events"):
        op.drop_table("flow_v2_events")
    inspector = inspect(bind)
    if _has_table(inspector, "flow_v2_sessions"):
        op.drop_table("flow_v2_sessions")

    inspector = inspect(bind)
    if _has_index(inspector, "flow_versions", "ix_flow_versions_v2_snapshot_hash"):
        op.drop_index("ix_flow_versions_v2_snapshot_hash", table_name="flow_versions")
    if _has_column(inspector, "flow_versions", "v2_snapshot_schema_version"):
        op.drop_column("flow_versions", "v2_snapshot_schema_version")
    if _has_column(inspector, "flow_versions", "v2_snapshot_hash"):
        op.drop_column("flow_versions", "v2_snapshot_hash")
