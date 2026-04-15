import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


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


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_leads_tenant_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, default=LeadStage.LEAD.value)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_stages.id"), nullable=True, index=True)
    temperature: Mapped[str] = mapped_column(String(16), nullable=False, default=LeadTemperature.COLD.value)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_interaction: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_contact_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
