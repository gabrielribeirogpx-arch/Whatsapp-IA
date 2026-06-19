from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ReplayEvent(BaseModel):
    event_type: str
    timestamp: str | None = None
    execution_id: str | None = None
    node_id: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayNode(BaseModel):
    node_id: str
    node_name: str | None = None
    node_type: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    status: str = "completed"
    execution_id: str | None = None
    events: list[ReplayEvent] = Field(default_factory=list)


class ReplayEdge(BaseModel):
    source: str
    target: str
    highlighted: bool = True
    execution_id: str | None = None
    order: int | None = None


class ReplayExecution(BaseModel):
    trace_id: str
    flow_id: str | None = None
    conversation_id: str | None = None
    contact_id: str | None = None
    tenant_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int = 0
    execution_ids: list[str] = Field(default_factory=list)
    nodes: list[ReplayNode] = Field(default_factory=list)
    edges: list[ReplayEdge] = Field(default_factory=list)
    timeline: list[ReplayEvent] = Field(default_factory=list)
    executions: dict[str, list[ReplayEvent]] = Field(default_factory=dict)
