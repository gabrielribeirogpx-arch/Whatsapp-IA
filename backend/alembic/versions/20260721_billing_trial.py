"""Add the internal Growth trial plan.

Revision ID: 20260721_billing_trial
Revises: 20260721_billing_foundation
"""
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260721_billing_trial"
down_revision = "20260721_billing_foundation"
branch_labels = None
depends_on = None

TRIAL_PLAN_ID = uuid.uuid5(uuid.NAMESPACE_URL, "wazza:billing-plan:growth_trial")

def upgrade() -> None:
    now = datetime.utcnow()
    plans = sa.table("plans", sa.column("id", postgresql.UUID(as_uuid=True)), sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("description", sa.Text()), sa.column("is_active", sa.Boolean()), sa.column("is_public", sa.Boolean()), sa.column("sort_order", sa.Integer()), sa.column("monthly_price_cents", sa.Integer()), sa.column("annual_price_cents", sa.Integer()), sa.column("currency", sa.String()), sa.column("metadata_json", postgresql.JSONB()), sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()))
    features = sa.table("plan_features", sa.column("id", postgresql.UUID(as_uuid=True)), sa.column("plan_id", postgresql.UUID(as_uuid=True)), sa.column("feature_key", sa.String()), sa.column("enabled", sa.Boolean()), sa.column("limit_value", sa.Integer()), sa.column("limit_unit", sa.String()), sa.column("metadata_json", postgresql.JSONB()), sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()))
    bind = op.get_bind()
    growth_id = bind.execute(sa.text("SELECT id FROM plans WHERE code = 'growth'")).scalar_one()
    bind.execute(plans.insert().values(id=TRIAL_PLAN_ID, code="growth_trial", name="Growth Trial", description="Período de teste interno com recursos do Growth.", is_active=True, is_public=False, sort_order=0, monthly_price_cents=0, annual_price_cents=0, currency="BRL", metadata_json={"internal": True}, created_at=now, updated_at=now))
    growth_features = bind.execute(sa.text("SELECT feature_key, enabled, limit_value, limit_unit, metadata_json FROM plan_features WHERE plan_id = :plan_id"), {"plan_id": growth_id}).mappings()
    bind.execute(features.insert(), [{"id": uuid.uuid4(), "plan_id": TRIAL_PLAN_ID, **dict(row), "created_at": now, "updated_at": now} for row in growth_features])

def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM plan_features WHERE plan_id = :plan_id"), {"plan_id": TRIAL_PLAN_ID})
    bind.execute(sa.text("DELETE FROM plans WHERE id = :plan_id"), {"plan_id": TRIAL_PLAN_ID})
