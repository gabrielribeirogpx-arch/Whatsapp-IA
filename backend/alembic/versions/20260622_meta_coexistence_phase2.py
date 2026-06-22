"""meta coexistence phase 2

Revision ID: 20260622_meta_coexistence_phase2
Revises: 20260622_meta_coexistence_phase1
Create Date: 2026-06-22
"""

from alembic import op

revision = "20260622_meta_coexistence_phase2"
down_revision = "20260622_meta_coex_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_whatsapp_providers ADD COLUMN IF NOT EXISTS business_manager_id varchar(120) NULL")
    op.execute("UPDATE tenant_whatsapp_providers SET business_manager_id = business_id WHERE business_manager_id IS NULL AND business_id IS NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS business_manager_id")
