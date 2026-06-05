"""add whatsapp provider connection validation fields

Revision ID: 20260607_provider_connection
Revises: 20260606_v2_snapshot_hash
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op

revision = "20260607_provider_connection"
down_revision = "20260606_v2_snapshot_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_whatsapp_providers
        ADD COLUMN IF NOT EXISTS connection_status VARCHAR(40) NOT NULL DEFAULT 'disconnected'
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_whatsapp_providers
        ADD COLUMN IF NOT EXISTS last_validation_at TIMESTAMP NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_whatsapp_providers
        ADD COLUMN IF NOT EXISTS last_validation_error TEXT NULL
        """
    )
    op.execute(
        """
        UPDATE tenant_whatsapp_providers
        SET connection_status = CASE
            WHEN status = 'connected' THEN 'connected'
            WHEN status = 'active' THEN 'connected'
            WHEN status = 'token_expired' THEN 'token_expired'
            WHEN status = 'invalid_token' THEN 'invalid_token'
            WHEN status = 'invalid_phone_number' THEN 'invalid_phone_number'
            WHEN status = 'meta_error' THEN 'meta_error'
            ELSE 'disconnected'
        END
        WHERE connection_status IS NULL OR connection_status = 'disconnected'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_whatsapp_providers_connection_status
        ON tenant_whatsapp_providers (tenant_id, connection_status)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_whatsapp_providers_connection_status")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS last_validation_error")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS last_validation_at")
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS connection_status")
