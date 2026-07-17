"""campaign analytics indexes

Revision ID: 20260717_cmp_idx
Revises: 20260622_meta_coexistence_phase1
Create Date: 2026-07-17
"""
from alembic import op

revision = "20260717_cmp_idx"
down_revision = "20260622_meta_coex_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaigns_tenant_created ON whatsapp_campaigns (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaigns_tenant_template ON whatsapp_campaigns (tenant_id, template_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaign_recipients_campaign_sent ON whatsapp_campaign_recipients (campaign_id, sent_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaign_recipients_campaign_delivered ON whatsapp_campaign_recipients (campaign_id, delivered_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaign_recipients_campaign_read ON whatsapp_campaign_recipients (campaign_id, read_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_campaign_recipients_campaign_failed ON whatsapp_campaign_recipients (campaign_id, failed_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaign_recipients_campaign_failed")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaign_recipients_campaign_read")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaign_recipients_campaign_delivered")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaign_recipients_campaign_sent")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaigns_tenant_template")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_campaigns_tenant_created")
