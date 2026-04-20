"""remove message column from conversations

Revision ID: 20260416_0016
Revises: 20260416_0015
Create Date: 2026-04-16 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260416_0016"
down_revision = "20260416_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("conversations", "message")


def downgrade() -> None:
    op.add_column("conversations", sa.Column("message", sa.Text(), nullable=True))
