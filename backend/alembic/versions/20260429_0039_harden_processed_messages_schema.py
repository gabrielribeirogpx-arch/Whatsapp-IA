"""harden processed_messages schema for global webhook idempotency

Revision ID: 20260429_0039
Revises: 20260429_0038
Create Date: 2026-04-29 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260429_0039"
down_revision = "20260429_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "processed_messages" not in tables:
        op.create_table(
            "processed_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("message_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_processed_messages_message_id", "processed_messages", ["message_id"], unique=True)
        return

    columns = {col["name"] for col in inspector.get_columns("processed_messages")}
    if "id" not in columns:
        op.add_column("processed_messages", sa.Column("id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute("UPDATE processed_messages SET id = gen_random_uuid() WHERE id IS NULL")
        op.alter_column("processed_messages", "id", nullable=False)

    indexes = {idx["name"] for idx in inspector.get_indexes("processed_messages")}
    if "ix_processed_messages_message_id" not in indexes:
        op.create_index("ix_processed_messages_message_id", "processed_messages", ["message_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "processed_messages" not in tables:
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("processed_messages")}
    if "ix_processed_messages_message_id" in indexes:
        op.drop_index("ix_processed_messages_message_id", table_name="processed_messages")
