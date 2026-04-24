"""add flow events table

Revision ID: 20260424_0030
Revises: 20260424_0029
Create Date: 2026-04-24 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260424_0030"
down_revision = "20260424_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["flow_nodes.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_flow_events_tenant_id"), "flow_events", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_flow_events_conversation_id"), "flow_events", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_flow_events_flow_id"), "flow_events", ["flow_id"], unique=False)
    op.create_index(op.f("ix_flow_events_node_id"), "flow_events", ["node_id"], unique=False)
    op.create_index(op.f("ix_flow_events_event_type"), "flow_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_flow_events_event_type"), table_name="flow_events")
    op.drop_index(op.f("ix_flow_events_node_id"), table_name="flow_events")
    op.drop_index(op.f("ix_flow_events_flow_id"), table_name="flow_events")
    op.drop_index(op.f("ix_flow_events_conversation_id"), table_name="flow_events")
    op.drop_index(op.f("ix_flow_events_tenant_id"), table_name="flow_events")
    op.drop_table("flow_events")
