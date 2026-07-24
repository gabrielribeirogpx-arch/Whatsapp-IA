"""Product analytics storage, deliberately separate from usage and observability."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ProductEvent(Base):
    __tablename__ = "product_events"
    __table_args__ = (Index("ix_product_events_tenant_event_time", "tenant_id", "event_name", "occurred_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(128)); anonymous_id: Mapped[str | None] = mapped_column(String(128))
    event_name: Mapped[str] = mapped_column(String(96), index=True); event_version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(24), default="backend")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True); received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    properties: Mapped[dict] = mapped_column(JSON, default=dict); context: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True); request_id: Mapped[str | None] = mapped_column(String(128)); correlation_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class ProductMetricDaily(Base):
    __tablename__ = "product_metric_daily"; __table_args__ = (UniqueConstraint("date", "tenant_id", "metric_name", "dimension_key", "dimension_value", name="uq_product_metric_daily"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True); date: Mapped[datetime] = mapped_column(Date, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True); metric_name: Mapped[str] = mapped_column(String(96)); dimension_key: Mapped[str] = mapped_column(String(64), default="all"); dimension_value: Mapped[str] = mapped_column(String(128), default="all"); metric_value: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True)); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class TenantActivationState(Base):
    __tablename__ = "tenant_activation_state"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    registration_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); onboarding_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); whatsapp_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_conversation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_flow_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_flow_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_message_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_message_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_ai_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_mcp_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); first_observability_view_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); billing_page_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); upgrade_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); checkout_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); subscription_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); activation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)); activation_score: Mapped[int] = mapped_column(Integer, default=0); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
