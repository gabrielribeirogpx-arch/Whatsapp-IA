"""create flow analytics events

Revision ID: 20260615_flow_analytics_events
Revises: 20260613_task_completion_fields
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260615_flow_analytics_events"
down_revision = "20260613_task_completion_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=False),
        sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id"), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("node_id", sa.String(length=128), nullable=True),
        sa.Column("node_type", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_key", sa.String(length=180), nullable=True),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_flow_analytics_tenant_flow_created", "flow_analytics_events", ["tenant_id", "flow_id", "created_at"])
    op.create_index("ix_flow_analytics_tenant_flow_type_created", "flow_analytics_events", ["tenant_id", "flow_id", "event_type", "created_at"])
    op.create_index("ix_flow_analytics_tenant_session", "flow_analytics_events", ["tenant_id", "session_id"])
    op.create_index("ix_flow_analytics_tenant_node", "flow_analytics_events", ["tenant_id", "node_id"])


def downgrade() -> None:
    op.drop_index("ix_flow_analytics_tenant_node", table_name="flow_analytics_events")
    op.drop_index("ix_flow_analytics_tenant_session", table_name="flow_analytics_events")
    op.drop_index("ix_flow_analytics_tenant_flow_type_created", table_name="flow_analytics_events")
    op.drop_index("ix_flow_analytics_tenant_flow_created", table_name="flow_analytics_events")
    op.drop_table("flow_analytics_events")
