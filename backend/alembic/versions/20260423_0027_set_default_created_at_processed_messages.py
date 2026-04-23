"""set default created_at for processed_messages

Revision ID: 20260423_0027
Revises: 20260423_0026
Create Date: 2026-04-23 00:10:00
"""

from alembic import op


revision = "20260423_0027"
down_revision = "20260423_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE processed_messages
        ALTER COLUMN created_at SET DEFAULT NOW();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE processed_messages
        ALTER COLUMN created_at DROP DEFAULT;
        """
    )
