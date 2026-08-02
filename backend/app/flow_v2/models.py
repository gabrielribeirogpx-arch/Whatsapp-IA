from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FlowV2Session(Base):
    """Minimal mutable pointer for Flow Runtime V2.

    Authoritative execution history lives in FlowV2Event. This table intentionally
    stores only routing metadata and the current pointer needed to resume work.
    """

    __tablename__ = "flow_v2_sessions"
    __table_args__ = (
        Index(
            "uq_flow_v2_active_session_identity",
            "tenant_id",
            "flow_version_id",
            "external_user_id",
            unique=True,
            postgresql_where=text("status IN ('running', 'waiting')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    flow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True, index=True
    )
    external_user_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running", server_default="running", index=True)
    current_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    last_event_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    events: Mapped[list["FlowV2Event"]] = relationship("FlowV2Event", back_populates="session", cascade="all, delete-orphan")


class FlowV2Event(Base):
    """Append-only event stream for Runtime V2 sessions."""

    __tablename__ = "flow_v2_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_index", name="uq_flow_v2_events_session_index"),
        UniqueConstraint("tenant_id", "input_message_id", "event_type", name="uq_flow_v2_events_input_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_v2_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    input_message_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    session: Mapped[FlowV2Session] = relationship("FlowV2Session", back_populates="events")


class FlowV2ScheduledJob(Base):
    """Scheduled resume point for Runtime V2 delay nodes."""

    __tablename__ = "flow_v2_scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_v2_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_node_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class FlowV2IdempotencyKey(Base):
    """Processed Runtime V2 ingress keys for production idempotency."""

    __tablename__ = "flow_v2_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_kind", "idempotency_key", name="uq_flow_v2_idempotency_key"),
        Index("ix_flow_v2_idempotency_tenant_kind", "tenant_id", "event_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_v2_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class FlowV2DeadLetter(Base):
    """Dead letter queue for failed Runtime V2 events."""

    __tablename__ = "flow_v2_dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_v2_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    flow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    error: Mapped[str] = mapped_column(Text, nullable=False)
    stacktrace: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
