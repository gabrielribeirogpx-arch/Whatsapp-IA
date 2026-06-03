"""flow runtime v2 sprint 6 hardening

Revision ID: 20260603_flow_v2_sprint6
Revises: 20260603_flow_v2_core
Create Date: 2026-06-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260603_flow_v2_sprint6"
down_revision = "20260603_flow_v2_core"
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

    if not _has_column(inspector, "flow_v2_events", "event_version"):
        op.add_column(
            "flow_v2_events",
            sa.Column("event_version", sa.Integer(), server_default="1", nullable=False),
        )

    if not _has_table(inspector, "flow_v2_idempotency_keys"):
        op.create_table(
            "flow_v2_idempotency_keys",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_kind", sa.String(length=32), nullable=False),
            sa.Column("idempotency_key", sa.String(length=180), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["flow_v2_sessions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "event_kind", "idempotency_key", name="uq_flow_v2_idempotency_key"),
        )

    inspector = inspect(bind)
    idempotency_indexes = {
        "ix_flow_v2_idempotency_keys_tenant_id": ["tenant_id"],
        "ix_flow_v2_idempotency_keys_event_kind": ["event_kind"],
        "ix_flow_v2_idempotency_keys_idempotency_key": ["idempotency_key"],
        "ix_flow_v2_idempotency_keys_session_id": ["session_id"],
        "ix_flow_v2_idempotency_keys_processed_at": ["processed_at"],
        "ix_flow_v2_idempotency_tenant_kind": ["tenant_id", "event_kind"],
    }
    for index_name, columns in idempotency_indexes.items():
        if not _has_index(inspector, "flow_v2_idempotency_keys", index_name):
            op.create_index(index_name, "flow_v2_idempotency_keys", columns, unique=False)

    if not _has_table(inspector, "flow_v2_dead_letters"):
        op.create_table(
            "flow_v2_dead_letters",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("event", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("stacktrace", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["flow_version_id"], ["flow_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["session_id"], ["flow_v2_sessions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    dead_letter_indexes = {
        "ix_flow_v2_dead_letters_tenant_id": ["tenant_id"],
        "ix_flow_v2_dead_letters_session_id": ["session_id"],
        "ix_flow_v2_dead_letters_flow_version_id": ["flow_version_id"],
        "ix_flow_v2_dead_letters_created_at": ["created_at"],
    }
    for index_name, columns in dead_letter_indexes.items():
        if not _has_index(inspector, "flow_v2_dead_letters", index_name):
            op.create_index(index_name, "flow_v2_dead_letters", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "flow_v2_dead_letters"):
        op.drop_table("flow_v2_dead_letters")
    inspector = inspect(bind)
    if _has_table(inspector, "flow_v2_idempotency_keys"):
        op.drop_table("flow_v2_idempotency_keys")
    inspector = inspect(bind)
    if _has_column(inspector, "flow_v2_events", "event_version"):
        op.drop_column("flow_v2_events", "event_version")
