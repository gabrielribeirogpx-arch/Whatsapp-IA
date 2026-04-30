"""add user state fields to flow_sessions

Revision ID: 20260430_flow_sessions_state
Revises: 20260415_add_name_to_conversations
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260430_flow_sessions_state"
down_revision = "20260415_add_name_to_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("flow_sessions", sa.Column("user_identifier", sa.String(), nullable=True))
    op.add_column("flow_sessions", sa.Column("variables", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.alter_column("flow_sessions", "conversation_id", existing_type=sa.String(), nullable=True)
    op.create_index("ix_flow_sessions_user_identifier", "flow_sessions", ["user_identifier"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_flow_sessions_user_identifier", table_name="flow_sessions")
    op.alter_column("flow_sessions", "conversation_id", existing_type=sa.String(), nullable=False)
    op.drop_column("flow_sessions", "variables")
    op.drop_column("flow_sessions", "user_identifier")
