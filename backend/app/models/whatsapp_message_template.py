import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WhatsAppMessageTemplate(Base):
    __tablename__ = "whatsapp_message_templates"
    __table_args__ = (
        Index("ix_whatsapp_message_templates_tenant_status", "tenant_id", "status"),
        Index("ix_whatsapp_message_templates_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_whatsapp_providers.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="pt_BR", server_default="pt_BR")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", server_default="draft")
    external_template_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    header_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    buttons_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    variables_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider: Mapped["TenantWhatsAppProvider | None"] = relationship("TenantWhatsAppProvider", back_populates="templates")

    @property
    def body_raw_meta(self) -> str:
        return self.body_text

    @property
    def body_preview(self) -> str | None:
        if isinstance(self.metadata_json, dict):
            return self.metadata_json.get("body_preview")
        return None
