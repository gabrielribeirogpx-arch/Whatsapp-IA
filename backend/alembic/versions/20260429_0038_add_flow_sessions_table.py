"""add flow_sessions table

Revision ID: 20260429_0038
Revises: 20260426_0037
Create Date: 2026-04-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260429_0038"
down_revision = "20260426_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "flow_sessions" not in tables:
        op.create_table(
            "flow_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", sa.String(), nullable=False),
            sa.Column("current_node_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flow_sessions_flow_id", "flow_sessions", ["flow_id"], unique=False)
        op.create_index("ix_flow_sessions_conversation_id", "flow_sessions", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_flow_sessions_conversation_id", table_name="flow_sessions")
    op.drop_index("ix_flow_sessions_flow_id", table_name="flow_sessions")
    op.drop_table("flow_sessions")
