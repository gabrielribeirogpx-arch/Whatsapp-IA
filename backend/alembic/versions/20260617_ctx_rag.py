"""flow v2 contextual retrieval session context

Revision ID: 20260617_ctx_rag
Revises: 20260616_flow_ai_conversation_messages
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260617_ctx_rag"
down_revision = "20260616_flow_ai_memory"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "flow_v2_sessions" in inspector.get_table_names() and not _has_column(inspector, "flow_v2_sessions", "context"):
        op.add_column(
            "flow_v2_sessions",
            sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "flow_v2_sessions" in inspector.get_table_names() and _has_column(inspector, "flow_v2_sessions", "context"):
        op.drop_column("flow_v2_sessions", "context")
