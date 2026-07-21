"""Add observational tenant usage counters.

Revision ID: 20260721_billing_usage
Revises: 20260721_billing_trial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260721_billing_usage"
down_revision = "20260721_billing_trial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("usage_counters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False), sa.Column("period_type", sa.String(24), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False), sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_value", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("reserved_value", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "metric_key", "period_start", "period_end", name="uq_usage_counter_period"),
    )
    op.create_index("ix_usage_counters_tenant", "usage_counters", ["tenant_id"])
    op.create_table("usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False), sa.Column("source_type", sa.String(64), nullable=False), sa.Column("source_id", sa.String(255), nullable=False), sa.Column("amount", sa.Numeric(20, 4), nullable=False), sa.Column("period_start", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "metric_key", "source_type", "source_id", name="uq_usage_event_source"),
    )
    op.create_index("ix_usage_events_tenant_id", "usage_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("usage_counters")
