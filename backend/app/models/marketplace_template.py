from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class MarketplaceTemplate(Base):
    __tablename__ = "marketplace_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    segment: Mapped[str] = mapped_column(String(80), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    versions: Mapped[list["MarketplaceTemplateVersion"]] = relationship(back_populates="template", cascade="all, delete-orphan")

class MarketplaceTemplateVersion(Base):
    __tablename__ = "marketplace_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_marketplace_template_version"), Index("ix_marketplace_template_versions_status", "status"))
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("marketplace_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    source_flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flows.id", ondelete="RESTRICT"), nullable=False)
    source_flow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="RESTRICT"), nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    nodes_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    edges_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    dependencies: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    validation_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    template: Mapped[MarketplaceTemplate] = relationship(back_populates="versions")
