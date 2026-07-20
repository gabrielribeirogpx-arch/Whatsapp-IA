from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TraceContext:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str | None = None
    conversation_id: str | None = None
    contact_id: str | None = None
    flow_id: str | None = None
    correlation_id: str | None = None
    message_id: str | None = None
    job_id: str | None = None
    parent_trace_id: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "TraceContext":
        payload = {**(data or {}), **{k: v for k, v in overrides.items() if v is not None}}
        return cls(
            trace_id=str(payload.get("trace_id")) if payload.get("trace_id") not in (None, "", "n/a", "N/A") else str(uuid.uuid4()),
            execution_id=str(payload.get("execution_id") or uuid.uuid4()),
            tenant_id=_str_or_none(payload.get("tenant_id")),
            conversation_id=_str_or_none(payload.get("conversation_id")),
            contact_id=_str_or_none(payload.get("contact_id")),
            flow_id=_str_or_none(payload.get("flow_id")),
            correlation_id=_str_or_none(payload.get("correlation_id")) or _str_or_none(payload.get("trace_id")),
            message_id=_str_or_none(payload.get("message_id")),
            job_id=_str_or_none(payload.get("job_id")),
            parent_trace_id=_str_or_none(payload.get("parent_trace_id")),
            started_at=payload.get("started_at") if isinstance(payload.get("started_at"), datetime) else datetime.utcnow(),
        )

    def as_metadata(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "execution_id": self.execution_id,
            "tenant_id": self.tenant_id,
            "conversation_id": self.conversation_id,
            "contact_id": self.contact_id,
            "flow_id": self.flow_id,
            "correlation_id": self.correlation_id or self.trace_id,
            "message_id": self.message_id,
            "job_id": self.job_id,
            "parent_trace_id": self.parent_trace_id,
            "started_at": self.started_at.isoformat(),
        }


def _str_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
