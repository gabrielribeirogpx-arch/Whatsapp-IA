"""Add canonical dashboard history timestamps and tenant timezone.

Revision ID: 20260926_dashboard_phase3
Revises: 20260913_audit_p0

No historical values are backfilled: updated_at and current final-stage state do
not prove when a conversion or completion happened.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260926_dashboard_phase3"
down_revision = "20260913_audit_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"))
    with op.batch_alter_table("leads") as batch:
        batch.add_column(sa.Column("converted_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_leads_tenant_converted_at", ["tenant_id", "converted_at"], unique=False)
    with op.batch_alter_table("flow_sessions") as batch:
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_flow_sessions_tenant_completed_at", ["tenant_id", "completed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("flow_sessions") as batch:
        batch.drop_index("ix_flow_sessions_tenant_completed_at")
        batch.drop_column("completed_at")
    with op.batch_alter_table("leads") as batch:
        batch.drop_index("ix_leads_tenant_converted_at")
        batch.drop_column("converted_at")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("timezone")
