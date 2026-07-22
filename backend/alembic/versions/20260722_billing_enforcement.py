"""Add non-destructive workspace billing access state.

Revision ID: 20260722_billing_enforcement
Revises: 20260721_stripe_billing
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_billing_enforcement"
down_revision = "20260721_stripe_billing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("workspace_access_mode", sa.String(length=32), nullable=False, server_default="full"))
    op.add_column("tenants", sa.Column("workspace_grace_period_ends_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("tenants", "workspace_grace_period_ends_at")
    op.drop_column("tenants", "workspace_access_mode")
