"""add bot rules table

Revision ID: 20260417_0016
Revises: 20260416_0015
Create Date: 2026-04-17 10:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260417_0016"
down_revision = "20260416_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=255), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("match_type", sa.String(length=20), nullable=False, server_default="contains"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bot_rules_tenant_id"), "bot_rules", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_rules_tenant_id"), table_name="bot_rules")
    op.drop_table("bot_rules")
