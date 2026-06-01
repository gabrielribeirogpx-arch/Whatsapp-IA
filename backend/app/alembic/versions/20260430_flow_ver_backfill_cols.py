"""ensure flow_versions tenant_id and snapshot columns exist safely

Revision ID: 20260430_flow_ver_backfill_cols
Revises: 20260430_flow_guard_backups
Create Date: 2026-04-30
"""

from alembic import op


revision = "20260430_flow_ver_backfill_cols"
down_revision = "20260430_flow_guard_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS snapshot JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE flow_versions DROP COLUMN IF EXISTS snapshot")
    op.execute("ALTER TABLE flow_versions DROP COLUMN IF EXISTS tenant_id")
