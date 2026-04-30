"""create tenants table

Revision ID: 0000_create_tenants_table
Revises:
Create Date: 2026-04-30 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0000_create_tenants_table"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("tenants")
