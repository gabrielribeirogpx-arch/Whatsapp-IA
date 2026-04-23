"""add processed_messages table for webhook idempotency

Revision ID: 20260423_0026
Revises: 20260418_0025
Create Date: 2026-04-23 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260423_0026"
down_revision = "20260418_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "processed_messages" not in tables:
        op.create_table(
            "processed_messages",
            sa.Column("message_id", sa.Text(), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("message_id"),
        )
        op.create_index("ix_processed_messages_tenant_id", "processed_messages", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_processed_messages_tenant_id", table_name="processed_messages")
    op.drop_table("processed_messages")
