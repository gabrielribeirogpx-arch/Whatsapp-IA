"""add conversation logs table

Revision ID: 20260418_0023
Revises: 20260418_0022
Create Date: 2026-04-18 13:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect


revision = "20260418_0023"
down_revision = "20260418_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "conversation_logs" not in tables:
        op.create_table(
            "conversation_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("intent", sa.String(), nullable=True),
            sa.Column("matched_rule", sa.String(), nullable=True),
            sa.Column("flow_step", sa.String(), nullable=True),
            sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("response", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("conversation_logs")}
    if "ix_conversation_logs_tenant_id" not in indexes:
        op.create_index("ix_conversation_logs_tenant_id", "conversation_logs", ["tenant_id"], unique=False)
    if "ix_conversation_logs_conversation_id" not in indexes:
        op.create_index("ix_conversation_logs_conversation_id", "conversation_logs", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conversation_logs_conversation_id", table_name="conversation_logs")
    op.drop_index("ix_conversation_logs_tenant_id", table_name="conversation_logs")
    op.drop_table("conversation_logs")
