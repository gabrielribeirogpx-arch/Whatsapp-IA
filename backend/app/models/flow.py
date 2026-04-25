from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    trigger_type: Mapped[str] = mapped_column(String, nullable=False, default="default", server_default="default", index=True)
    trigger_value: Mapped[str | None] = mapped_column(String, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_words: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flow_versions.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps: Mapped[list["FlowStep"]] = relationship("FlowStep", back_populates="flow", cascade="all, delete-orphan")
    nodes: Mapped[list["FlowNode"]] = relationship("FlowNode", cascade="all, delete-orphan")
    versions: Mapped[list["FlowVersion"]] = relationship(
        "FlowVersion",
        back_populates="flow",
        cascade="all, delete-orphan",
        foreign_keys="FlowVersion.flow_id",
    )
    current_version: Mapped["FlowVersion | None"] = relationship(
        "FlowVersion",
        foreign_keys=[current_version_id],
        post_update=True,
    )


class FlowStep(Base):
    __tablename__ = "flow_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flows.id"), nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected_inputs: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    next_step_map: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    flow: Mapped[Flow] = relationship(Flow, back_populates="steps")


class FlowNode(Base):
    __tablename__ = "flow_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flows.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    position_x: Mapped[int | None] = mapped_column(nullable=True)
    position_y: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FlowEdge(Base):
    __tablename__ = "flow_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flows.id"), nullable=False, index=True)
    source: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False)
    target: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)


class FlowVersion(Base):
    __tablename__ = "flow_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flows.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column("version", Integer, nullable=False)
    nodes_json: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    edges_json: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    flow: Mapped[Flow] = relationship("Flow", back_populates="versions", foreign_keys=[flow_id])

