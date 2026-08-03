"""Persist interactive reply titles for Inbox presentation.

Revision ID: 20260803_inbox_titles
Revises: 20260802_flow_v2_vars
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_inbox_titles"
down_revision = "20260802_flow_v2_vars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("interactive_title", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "interactive_title")
