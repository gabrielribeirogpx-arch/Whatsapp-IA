import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantMixin


class LeadStage(StrEnum):
    LEAD = "lead"
    QUALIFICADO = "qualificado"
    PROPOSTA = "proposta"
    FECHADO = "fechado"
    PERDIDO = "perdido"


class LeadTemperature(StrEnum):
    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


class LeadSource(StrEnum):
    WHATSAPP = "whatsapp"
    WEBCHAT = "webchat"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    MANUAL = "manual"
    API = "api"


class LeadStatus(StrEnum):
    ACTIVE = "active"
    CONVERTED = "converted"
    DELETED = "deleted"


class Lead(TenantMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_leads_tenant_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, default=LeadStage.LEAD.value)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_stages.id"), nullable=True, index=True)
    temperature: Mapped[str] = mapped_column(String(16), nullable=False, default=LeadTemperature.COLD.value)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default=LeadSource.WHATSAPP.value, server_default=LeadSource.WHATSAPP.value)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=LeadStatus.ACTIVE.value, server_default=LeadStatus.ACTIVE.value)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_interaction: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_contact_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    entered_stage_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
