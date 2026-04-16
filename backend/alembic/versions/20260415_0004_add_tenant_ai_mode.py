"""add ai_mode to tenants

Revision ID: 20260415_0004
Revises: 20260407_0003
Create Date: 2026-04-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260415_0004"
down_revision = "20260407_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("tenants")]
    check_constraints = [constraint["name"] for constraint in inspector.get_check_constraints("tenants")]

    if "ai_mode" not in columns:
        op.add_column(
            "tenants",
            sa.Column("ai_mode", sa.String(length=32), nullable=False, server_default="atendente"),
        )

    if "ck_tenants_ai_mode" not in check_constraints:
        op.create_check_constraint(
            "ck_tenants_ai_mode",
            "tenants",
            "ai_mode IN ('atendente', 'vendedor')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = [col["name"] for col in inspector.get_columns("tenants")]
    check_constraints = [constraint["name"] for constraint in inspector.get_check_constraints("tenants")]

    if "ck_tenants_ai_mode" in check_constraints:
        op.drop_constraint("ck_tenants_ai_mode", "tenants", type_="check")

    if "ai_mode" in columns:
        op.drop_column("tenants", "ai_mode")
