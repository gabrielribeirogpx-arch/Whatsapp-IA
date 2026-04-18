"""add conversation_state to conversations

Revision ID: 20260418_0020
Revises: 20260418_0019
Create Date: 2026-04-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0020"
down_revision = "20260418_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("conversation_state", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "conversation_state")
