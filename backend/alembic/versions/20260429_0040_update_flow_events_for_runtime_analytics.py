"""update flow_events for runtime analytics

Revision ID: 20260429_0040
Revises: 20260429_0039
Create Date: 2026-04-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_0040"
down_revision = "20260429_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flow_events", sa.Column("data", sa.JSON(), nullable=True))
    op.execute("UPDATE flow_events SET data = '{}'::json WHERE data IS NULL")
    op.alter_column("flow_events", "data", nullable=False)

    op.drop_constraint("flow_events_tenant_id_fkey", "flow_events", type_="foreignkey")
    op.alter_column("flow_events", "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    op.drop_constraint("flow_events_conversation_id_fkey", "flow_events", type_="foreignkey")
    op.alter_column(
        "flow_events",
        "conversation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(),
        postgresql_using="conversation_id::text",
        nullable=False,
    )

    op.drop_constraint("flow_events_node_id_fkey", "flow_events", type_="foreignkey")
    op.alter_column(
        "flow_events",
        "node_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(),
        postgresql_using="node_id::text",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "flow_events",
        "node_id",
        existing_type=sa.String(),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="NULLIF(node_id, '')::uuid",
        nullable=True,
    )
    op.create_foreign_key("flow_events_node_id_fkey", "flow_events", "flow_nodes", ["node_id"], ["id"])

    op.alter_column(
        "flow_events",
        "conversation_id",
        existing_type=sa.String(),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="conversation_id::uuid",
        nullable=False,
    )
    op.create_foreign_key("flow_events_conversation_id_fkey", "flow_events", "conversations", ["conversation_id"], ["id"])

    op.alter_column("flow_events", "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_foreign_key("flow_events_tenant_id_fkey", "flow_events", "tenants", ["tenant_id"], ["id"])

    op.drop_column("flow_events", "data")
