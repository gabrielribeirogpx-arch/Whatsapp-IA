from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class MarketplaceInstallation(Base):
    __tablename__ = "marketplace_installations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_marketplace_installation_tenant_key"), Index("ix_marketplace_installations_tenant_slug", "tenant_id", "template_slug"), Index("ix_marketplace_installations_tenant_status", "tenant_id", "status"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(120), nullable=False)
    template_slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    template_type: Mapped[str] = mapped_column(String(40), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    automation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    variant: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    installed_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_resources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dependency_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    manifest_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    customization_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    resources: Mapped[list["MarketplaceInstallationResource"]] = relationship(cascade="all, delete-orphan", back_populates="installation")

class MarketplaceInstallationResource(Base):
    __tablename__ = "marketplace_installation_resources"
    __table_args__ = (UniqueConstraint("installation_id", "resource_type", "resource_id", name="uq_marketplace_installation_resource"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("marketplace_installations.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(200), nullable=False)
    creation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    rollback_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_requested")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    installation: Mapped[MarketplaceInstallation] = relationship(back_populates="resources")
