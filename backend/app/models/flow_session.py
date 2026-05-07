from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FlowSession(Base):
    __tablename__ = "flow_sessions"
    __table_args__ = (
        Index("ix_flow_sessions_tenant_flow_started_at", "tenant_id", "flow_id", "started_at"),
        Index(
            "ix_flow_sessions_tenant_flow_completion_started_at",
            "tenant_id",
            "flow_id",
            "completion_status",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_identifier: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    current_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running", server_default="running")
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    variables: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default="now()")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_event_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default="now()", index=True)
    completion_status: Mapped[str] = mapped_column(String, nullable=False, default="running", server_default="running")
    conversion_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    abandon_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
