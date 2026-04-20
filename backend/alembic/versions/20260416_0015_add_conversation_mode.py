"""add mode field to conversations

Revision ID: 20260416_0015
Revises: 20260415_0014
Create Date: 2026-04-16 00:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260416_0015"
down_revision = "20260415_0014"
branch_labels = None
depends_on = None



def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("mode", sa.String(), nullable=False, server_default="human"),
    )



def downgrade() -> None:
    op.drop_column("conversations", "mode")
