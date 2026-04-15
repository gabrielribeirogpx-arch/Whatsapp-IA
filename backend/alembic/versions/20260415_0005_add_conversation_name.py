"""add name to conversations

Revision ID: 20260415_0005
Revises: 20260415_0004
Create Date: 2026-04-15 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0005"
down_revision = "20260415_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "name")
