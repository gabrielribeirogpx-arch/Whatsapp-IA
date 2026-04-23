"""set default created_at for processed_messages

Revision ID: 20260423_0027
Revises: 20260423_0026
Create Date: 2026-04-23 00:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260423_0027"
down_revision = "20260423_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "processed_messages",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


def downgrade() -> None:
    op.alter_column(
        "processed_messages",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
