"""meta coexistence phase 1

Revision ID: 20260622_meta_coex_phase1
Revises: 20260607_provider_connection
Create Date: 2026-06-22
"""

from alembic import op

revision = "20260622_meta_coex_phase1"
down_revision = "20260607_provider_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tenant_whatsapp_providers
        ADD COLUMN IF NOT EXISTS connection_type varchar(40) NOT NULL DEFAULT 'cloud_api',
        ADD COLUMN IF NOT EXISTS coexistence_enabled boolean NOT NULL DEFAULT false,
        ADD COLUMN IF NOT EXISTS coexistence_status varchar(80) NULL,
        ADD COLUMN IF NOT EXISTS business_phone_number_id varchar(120) NULL,
        ADD COLUMN IF NOT EXISTS phone_display_name varchar(120) NULL,
        ADD COLUMN IF NOT EXISTS phone_verified_name varchar(120) NULL,
        ADD COLUMN IF NOT EXISTS onboarding_metadata jsonb NULL
    """)
    op.execute("UPDATE tenant_whatsapp_providers SET connection_type = 'cloud_api' WHERE connection_type IS NULL OR btrim(connection_type) = ''")
    op.execute("UPDATE tenant_whatsapp_providers SET coexistence_enabled = false WHERE coexistence_enabled IS NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS onboarding_metadata")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS phone_verified_name")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS phone_display_name")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS business_phone_number_id")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS coexistence_status")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS coexistence_enabled")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS connection_type")
