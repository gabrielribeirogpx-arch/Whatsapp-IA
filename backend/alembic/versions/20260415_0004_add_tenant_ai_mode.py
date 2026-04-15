"""add ai_mode to tenants

Revision ID: 20260415_0004
Revises: 20260407_0003
Create Date: 2026-04-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0004"
down_revision = "20260407_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("ai_mode", sa.String(length=32), nullable=False, server_default="atendente"),
    )
    op.create_check_constraint(
        "ck_tenants_ai_mode",
        "tenants",
        "ai_mode IN ('atendente', 'vendedor')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenants_ai_mode", "tenants", type_="check")
    op.drop_column("tenants", "ai_mode")
