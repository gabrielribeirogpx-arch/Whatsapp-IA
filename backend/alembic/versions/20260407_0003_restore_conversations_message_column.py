"""restore conversations.message column if missing

Revision ID: 20260407_0003
Revises: 20260407_0002
Create Date: 2026-04-07 00:20:00
"""

from alembic import op


revision = "20260407_0003"
down_revision = "20260407_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS message TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS message")
