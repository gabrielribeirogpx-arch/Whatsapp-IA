"""add intent_history and last_intent_at to conversations

Revision ID: 20260418_0019
Revises: 20260418_0018
Create Date: 2026-04-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0019"
down_revision = "20260418_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("intent_history", sa.JSON(), nullable=True))
    op.add_column("conversations", sa.Column("last_intent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "last_intent_at")
    op.drop_column("conversations", "intent_history")
