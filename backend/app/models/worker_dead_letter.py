from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerDeadLetter(Base):
    __tablename__ = "worker_dead_letters"
    __table_args__ = (
        Index("ix_worker_dead_letters_tenant_id", "tenant_id"),
        Index("ix_worker_dead_letters_job_type", "job_type"),
        Index("ix_worker_dead_letters_created_at", "created_at"),
        Index("ix_worker_dead_letters_resolved_at", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    queue_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    job_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
