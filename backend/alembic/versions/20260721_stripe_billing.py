"""Add Stripe billing catalog and idempotent webhook event ledger.

Revision ID: 20260721_stripe_billing
Revises: 20260721_billing_usage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "20260721_stripe_billing"
down_revision = "20260721_billing_usage"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("plan_prices", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False), sa.Column("provider", sa.String(32), nullable=False), sa.Column("billing_interval", sa.String(16), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("external_product_id", sa.String(255)), sa.Column("external_price_id", sa.String(255), nullable=False), sa.Column("amount_cents", sa.Integer(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("provider", "external_price_id", name="uq_plan_prices_provider_external_price"))
    op.create_index("ix_plan_prices_plan_provider", "plan_prices", ["plan_id", "provider"])
    op.create_table("billing_events", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("provider", sa.String(32), nullable=False), sa.Column("external_event_id", sa.String(255), nullable=False), sa.Column("event_type", sa.String(100), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("received_at", sa.DateTime(), nullable=False), sa.Column("processing_started_at", sa.DateTime()), sa.Column("processed_at", sa.DateTime()), sa.Column("error_code", sa.String(80)), sa.Column("error_message", sa.String(500)), sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"), sa.UniqueConstraint("provider", "external_event_id", name="uq_billing_events_provider_external_event"))
    op.create_index("ix_subscriptions_external_subscription_id", "subscriptions", ["external_subscription_id"], unique=True, postgresql_where=sa.text("external_subscription_id IS NOT NULL"))
def downgrade():
    op.drop_index("ix_subscriptions_external_subscription_id", table_name="subscriptions"); op.drop_table("billing_events"); op.drop_index("ix_plan_prices_plan_provider", table_name="plan_prices"); op.drop_table("plan_prices")
