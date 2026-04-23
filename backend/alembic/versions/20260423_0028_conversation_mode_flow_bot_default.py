"""set conversation mode default to bot and normalize values

Revision ID: 20260423_0028
Revises: 20260423_0027
Create Date: 2026-04-23 00:28:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260423_0028"
down_revision = "20260423_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "conversations",
        "mode",
        existing_type=sa.String(),
        type_=sa.String(length=10),
        existing_nullable=False,
        server_default="bot",
    )
    op.execute("UPDATE conversations SET mode = 'bot' WHERE mode IS NULL OR mode NOT IN ('bot', 'flow')")


def downgrade() -> None:
    op.alter_column(
        "conversations",
        "mode",
        existing_type=sa.String(length=10),
        type_=sa.String(),
        existing_nullable=False,
        server_default="human",
    )
