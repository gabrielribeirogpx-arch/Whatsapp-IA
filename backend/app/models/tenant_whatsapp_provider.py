import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TenantWhatsAppProvider(Base):
    __tablename__ = "tenant_whatsapp_providers"
    __table_args__ = (
        Index("ix_tenant_whatsapp_providers_tenant_provider", "tenant_id", "provider_type"),
        Index("ix_tenant_whatsapp_providers_tenant_active", "tenant_id", "is_active"),
        Index(
            "uq_tenant_whatsapp_provider_phone_number_owner",
            "phone_number_id",
            unique=True,
            postgresql_where=text("phone_number_id IS NOT NULL AND btrim(phone_number_id) <> ''"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    waba_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    connection_type: Mapped[str] = mapped_column(String(40), nullable=False, default="cloud_api", server_default="cloud_api")
    coexistence_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    coexistence_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    business_phone_number_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_verified_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onboarding_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    bsp_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    app_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_verify_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="disconnected", server_default="disconnected")
    connection_status: Mapped[str] = mapped_column(String(40), nullable=False, default="disconnected", server_default="disconnected")
    last_validation_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_connection_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    templates: Mapped[list["WhatsAppMessageTemplate"]] = relationship(
        "WhatsAppMessageTemplate", back_populates="provider", cascade="all, delete-orphan"
    )
