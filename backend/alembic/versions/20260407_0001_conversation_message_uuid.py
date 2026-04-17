"""create conversations and messages tables with uuid ids

Revision ID: 20260407_0001
Revises: 
Create Date: 2026-04-07 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "conversations" not in table_names:
        op.create_table(
            "conversations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("phone_number", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "messages" not in table_names:
        op.create_table(
            "messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("text", sa.String(), nullable=False),
            sa.Column("from_me", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(bind)
    conversations_indexes = {index["name"] for index in inspector.get_indexes("conversations")}
    conversations_phone_index = op.f("ix_conversations_phone_number")
    if conversations_phone_index not in conversations_indexes:
        op.create_index(conversations_phone_index, "conversations", ["phone_number"], unique=False)

    messages_indexes = {index["name"] for index in inspector.get_indexes("messages")}
    messages_conversation_index = op.f("ix_messages_conversation_id")
    if messages_conversation_index not in messages_indexes:
        op.create_index(messages_conversation_index, "messages", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_phone_number"), table_name="conversations")
    op.drop_table("conversations")
