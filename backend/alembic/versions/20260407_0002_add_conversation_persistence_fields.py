"""add phone/message/response fields to conversations

Revision ID: 20260407_0002
Revises: 20260407_0001
Create Date: 2026-04-07 00:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260407_0002"
down_revision = "20260407_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("phone", sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("message", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("response", sa.Text(), nullable=True))
    op.alter_column("conversations", "phone_number", existing_type=sa.String(), nullable=True)
    op.create_index(op.f("ix_conversations_phone"), "conversations", ["phone"], unique=False)
    op.execute("UPDATE conversations SET phone = phone_number WHERE phone IS NULL")


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_phone"), table_name="conversations")
    op.alter_column("conversations", "phone_number", existing_type=sa.String(), nullable=False)
    op.drop_column("conversations", "response")
    op.drop_column("conversations", "message")
    op.drop_column("conversations", "phone")
