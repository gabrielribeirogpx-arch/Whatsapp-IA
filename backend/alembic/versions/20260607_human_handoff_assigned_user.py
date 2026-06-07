"""add conversation assigned user for human handoff badges

Revision ID: 20260607_handoff_assignment
Revises: 20260608_single_active_flow
Create Date: 2026-06-07 00:00:00.000000
"""

from alembic import op


revision = "20260607_handoff_assignment"
down_revision = "20260608_single_active_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS assigned_user_id UUID")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS assigned_user_id")
