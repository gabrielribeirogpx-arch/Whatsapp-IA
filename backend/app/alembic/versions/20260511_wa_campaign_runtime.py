"""whatsapp campaigns runtime

Revision ID: 20260511_wa_campaign_runtime
Revises: 20260510_whatsapp_business
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260511_wa_campaign_runtime"
down_revision = "20260510_whatsapp_business"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("total_recipients", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_delivered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["tenant_whatsapp_providers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["whatsapp_message_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_campaigns_tenant_id", "whatsapp_campaigns", ["tenant_id"])
    op.create_index("ix_whatsapp_campaigns_provider_id", "whatsapp_campaigns", ["provider_id"])
    op.create_index("ix_whatsapp_campaigns_template_id", "whatsapp_campaigns", ["template_id"])
    op.create_index("ix_whatsapp_campaigns_tenant_status", "whatsapp_campaigns", ["tenant_id", "status"])

    op.create_table(
        "whatsapp_campaign_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("variables_json", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("provider_message_id", sa.String(length=180), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("template_category", sa.String(length=32), nullable=True),
        sa.Column("conversation_id", sa.String(length=120), nullable=True),
        sa.Column("pricing_json", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["whatsapp_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_campaign_recipients_campaign_id", "whatsapp_campaign_recipients", ["campaign_id"])
    op.create_index("ix_whatsapp_campaign_recipients_campaign_status", "whatsapp_campaign_recipients", ["campaign_id", "status"])
    op.create_index("ix_whatsapp_campaign_recipients_provider_message", "whatsapp_campaign_recipients", ["provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_campaign_recipients_provider_message", table_name="whatsapp_campaign_recipients")
    op.drop_index("ix_whatsapp_campaign_recipients_campaign_status", table_name="whatsapp_campaign_recipients")
    op.drop_index("ix_whatsapp_campaign_recipients_campaign_id", table_name="whatsapp_campaign_recipients")
    op.drop_table("whatsapp_campaign_recipients")
    op.drop_index("ix_whatsapp_campaigns_tenant_status", table_name="whatsapp_campaigns")
    op.drop_index("ix_whatsapp_campaigns_template_id", table_name="whatsapp_campaigns")
    op.drop_index("ix_whatsapp_campaigns_provider_id", table_name="whatsapp_campaigns")
    op.drop_index("ix_whatsapp_campaigns_tenant_id", table_name="whatsapp_campaigns")
    op.drop_table("whatsapp_campaigns")
