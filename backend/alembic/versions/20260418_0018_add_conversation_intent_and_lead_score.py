"""add last_intent and lead_score to conversations

Revision ID: 20260418_0018
Revises: 20260418_0017
Create Date: 2026-04-18 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0018"
down_revision = "20260418_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("last_intent", sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("lead_score", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("conversations", "lead_score")
    op.drop_column("conversations", "last_intent")
