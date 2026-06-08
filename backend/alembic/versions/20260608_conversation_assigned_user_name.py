"""persist assigned user name on conversations

Revision ID: 20260608_assigned_user_name
Revises: 20260607_handoff_assignment
Create Date: 2026-06-08
"""

from alembic import op


revision = "20260608_assigned_user_name"
down_revision = "20260607_handoff_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS assigned_user_name VARCHAR(150)")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS assigned_user_name")
