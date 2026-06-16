"""flow ai conversation messages

Revision ID: 20260616_flow_ai_memory
Revises: 20260616_split_ai_models
Create Date: 2026-06-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260616_flow_ai_memory"
down_revision = "20260616_split_ai_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_ai_conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_v2_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_flow_ai_memory_tenant_session_created", "flow_ai_conversation_messages", ["tenant_id", "session_id", "created_at"])
    op.create_index("ix_flow_ai_memory_tenant_conversation_created", "flow_ai_conversation_messages", ["tenant_id", "conversation_id", "created_at"])
    op.create_index("ix_flow_ai_memory_tenant_flow_created", "flow_ai_conversation_messages", ["tenant_id", "flow_id", "created_at"])
    op.create_index("ix_flow_ai_memory_tenant_node_created", "flow_ai_conversation_messages", ["tenant_id", "node_id", "created_at"])


def downgrade() -> None:
    op.drop_table("flow_ai_conversation_messages")
