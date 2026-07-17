import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WhatsAppCampaign(Base):
    __tablename__ = "whatsapp_campaigns"
    __table_args__ = (
        Index("ix_whatsapp_campaigns_tenant_status", "tenant_id", "status"),
        Index("ix_whatsapp_campaigns_tenant_scheduled", "tenant_id", "scheduled_at"),
        Index("ix_whatsapp_campaigns_tenant_created", "tenant_id", "created_at"),
        Index("ix_whatsapp_campaigns_tenant_template", "tenant_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_whatsapp_providers.id", ondelete="RESTRICT"), nullable=False, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("whatsapp_message_templates.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_delivered: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    recipients: Mapped[list["WhatsAppCampaignRecipient"]] = relationship(
        "WhatsAppCampaignRecipient", back_populates="campaign", cascade="all, delete-orphan"
    )


class WhatsAppCampaignRecipient(Base):
    __tablename__ = "whatsapp_campaign_recipients"
    __table_args__ = (
        Index("ix_whatsapp_campaign_recipients_campaign_status", "campaign_id", "status"),
        Index("ix_whatsapp_campaign_recipients_provider_message", "provider_message_id"),
        Index("ix_whatsapp_campaign_recipients_campaign_sent", "campaign_id", "sent_at"),
        Index("ix_whatsapp_campaign_recipients_campaign_delivered", "campaign_id", "delivered_at"),
        Index("ix_whatsapp_campaign_recipients_campaign_read", "campaign_id", "read_at"),
        Index("ix_whatsapp_campaign_recipients_campaign_failed", "campaign_id", "failed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    variables_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pricing_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaign: Mapped["WhatsAppCampaign"] = relationship("WhatsAppCampaign", back_populates="recipients")
