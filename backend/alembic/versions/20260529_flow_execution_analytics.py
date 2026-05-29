"""persist flow executions and execution events

Revision ID: 20260529_flow_execution_analytics
Revises: 20260529_crm_operational
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260529_flow_execution_analytics"
down_revision = "20260529_crm_operational"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_columns(table)} if inspector.has_table(table) else set()
    if column.name not in existing:
        op.add_column(table, column)


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table)} if inspector.has_table(table) else set()
    if name not in existing:
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("flow_executions"):
        op.create_table(
            "flow_executions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=True),
            sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id"), nullable=True),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True),
            sa.Column("flow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id"), nullable=True),
            sa.Column("user_phone", sa.String(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
            sa.Column("current_node", sa.String(), nullable=True),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("current_node_id", sa.String(), nullable=True),
            sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
    else:
        _add_column_if_missing("flow_executions", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id"), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("contact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("contacts.id"), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")))
        _add_column_if_missing("flow_executions", sa.Column("completed_at", sa.DateTime(), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("status", sa.String(length=40), nullable=False, server_default="running"))
        _add_column_if_missing("flow_executions", sa.Column("current_node", sa.String(), nullable=True))
        _add_column_if_missing("flow_executions", sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        op.execute("ALTER TABLE flow_executions ALTER COLUMN flow_version_id DROP NOT NULL")
        op.execute("ALTER TABLE flow_executions ALTER COLUMN user_phone DROP NOT NULL")

    if not inspector.has_table("flow_execution_events"):
        op.create_table(
            "flow_execution_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_executions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("node_id", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )

    for table, columns in {
        "flow_executions": ["tenant_id", "flow_id", "contact_id", "conversation_id", "started_at", "status", "completed"],
        "flow_execution_events": ["execution_id", "node_id", "event_type", "created_at"],
    }.items():
        for column in columns:
            _create_index_if_missing(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("flow_execution_events")
