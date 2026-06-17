from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FlowAILongTermMemory(Base):
    __tablename__ = "flow_ai_long_term_memory"
    __table_args__ = (
        Index("ix_flow_ai_ltm_tenant_id", "tenant_id"),
        Index("ix_flow_ai_ltm_contact_id", "contact_id"),
        Index("ix_flow_ai_ltm_conversation_id", "conversation_id"),
        Index("ix_flow_ai_ltm_fact_type", "fact_type"),
        Index("ix_flow_ai_ltm_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("flow_v2_sessions.id", ondelete="SET NULL"), nullable=True)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    fact_embedding_json: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    importance_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.5)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
