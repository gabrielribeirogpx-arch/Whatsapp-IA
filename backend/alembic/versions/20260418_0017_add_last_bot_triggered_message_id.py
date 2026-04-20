"""add last_bot_triggered_message_id to conversations

Revision ID: 20260418_0017
Revises: 20260417_0016
Create Date: 2026-04-18 09:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260418_0017"
down_revision = "20260417_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_bot_triggered_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "last_bot_triggered_message_id")
