"""create pending actions

Revision ID: 20260621_pending_actions
Revises: 20260620_integration_connections
Create Date: 2026-06-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260621_pending_actions"
down_revision = "20260620_integration_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pending_actions_tenant_id", "pending_actions", ["tenant_id"])
    op.create_index("ix_pending_actions_conversation_id", "pending_actions", ["conversation_id"])
    op.create_index("ix_pending_actions_action_type", "pending_actions", ["action_type"])
    op.create_index("ix_pending_actions_tenant_conversation", "pending_actions", ["tenant_id", "conversation_id"])
    op.create_index("ix_pending_actions_tenant_action_type", "pending_actions", ["tenant_id", "action_type"])


def downgrade() -> None:
    op.drop_index("ix_pending_actions_tenant_action_type", table_name="pending_actions")
    op.drop_index("ix_pending_actions_tenant_conversation", table_name="pending_actions")
    op.drop_index("ix_pending_actions_action_type", table_name="pending_actions")
    op.drop_index("ix_pending_actions_conversation_id", table_name="pending_actions")
    op.drop_index("ix_pending_actions_tenant_id", table_name="pending_actions")
    op.drop_table("pending_actions")
