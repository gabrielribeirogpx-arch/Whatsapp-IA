"""worker dead letters

Revision ID: 20260618_worker_dlq
Revises: 20260618_tenant_mcp
Create Date: 2026-06-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260618_worker_dlq"
down_revision = "20260618_tenant_mcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_dead_letters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("queue_name", sa.String(length=80), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_worker_dead_letters_tenant_id", "worker_dead_letters", ["tenant_id"])
    op.create_index("ix_worker_dead_letters_job_type", "worker_dead_letters", ["job_type"])
    op.create_index("ix_worker_dead_letters_created_at", "worker_dead_letters", ["created_at"])
    op.create_index("ix_worker_dead_letters_resolved_at", "worker_dead_letters", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_dead_letters_resolved_at", table_name="worker_dead_letters")
    op.drop_index("ix_worker_dead_letters_created_at", table_name="worker_dead_letters")
    op.drop_index("ix_worker_dead_letters_job_type", table_name="worker_dead_letters")
    op.drop_index("ix_worker_dead_letters_tenant_id", table_name="worker_dead_letters")
    op.drop_table("worker_dead_letters")
