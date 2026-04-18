"""add last_bot_question and current_objective to conversations

Revision ID: 20260418_0021
Revises: 20260418_0020
Create Date: 2026-04-18 00:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0021"
down_revision = "20260418_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("last_bot_question", sa.String(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("current_objective", sa.String(), nullable=False, server_default="venda"),
    )


def downgrade() -> None:
    op.drop_column("conversations", "current_objective")
    op.drop_column("conversations", "last_bot_question")
