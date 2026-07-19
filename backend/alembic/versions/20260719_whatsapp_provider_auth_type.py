"""preserve manual WhatsApp providers alongside Meta Embedded Signup

Revision ID: 20260719_wp_auth_type
Revises: 20260717_merge_meta_campaign
Create Date: 2026-07-19
"""

from alembic import op


revision = "20260719_wp_auth_type"
down_revision = "20260717_merge_meta_campaign"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing providers predate Embedded Signup and are therefore manual.
    # The default also protects providers created by older application versions.
    op.execute(
        "ALTER TABLE tenant_whatsapp_providers "
        "ADD COLUMN IF NOT EXISTS auth_type varchar(40) NOT NULL DEFAULT 'manual'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_whatsapp_providers DROP COLUMN IF EXISTS auth_type")
