"""add avatar_url to conversations

Revision ID: 20260415_0008
Revises: 20260415_0007
Create Date: 2026-04-15 03:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0008"
down_revision = "20260415_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("avatar_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "avatar_url")
