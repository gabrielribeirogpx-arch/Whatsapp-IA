"""ensure user_identifier exists on flow_sessions

Revision ID: 20260430_flow_sessions_user_identifier_safe
Revises: 20260430_flow_guardrails_and_backups
Create Date: 2026-04-30
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260430_flow_sessions_user_identifier_safe"
down_revision = "20260430_flow_guardrails_and_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE flow_sessions
        ADD COLUMN IF NOT EXISTS user_identifier VARCHAR(255);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE flow_sessions
        DROP COLUMN IF EXISTS user_identifier;
        """
    )
