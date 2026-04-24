"""add context, last_input and retries to conversations

Revision ID: 20260424_0029
Revises: 20260423_0028
Create Date: 2026-04-24 00:29:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260424_0029"
down_revision = "20260423_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}

    if "context" not in conversation_columns:
        op.add_column("conversations", sa.Column("context", sa.JSON(), nullable=True))
    if "last_input" not in conversation_columns:
        op.add_column("conversations", sa.Column("last_input", sa.String(), nullable=True))
    if "retries" not in conversation_columns:
        op.add_column("conversations", sa.Column("retries", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}

    if "retries" in conversation_columns:
        op.drop_column("conversations", "retries")
    if "last_input" in conversation_columns:
        op.drop_column("conversations", "last_input")
    if "context" in conversation_columns:
        op.drop_column("conversations", "context")
