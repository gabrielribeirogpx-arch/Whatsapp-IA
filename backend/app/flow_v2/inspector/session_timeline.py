from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.models import FlowV2Event


@dataclass(frozen=True)
class TimelineEntry:
    event_index: int
    event_type: str
    node_id: str | None
    payload: dict[str, Any]
    input_message_id: str | None = None
    created_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_index": self.event_index,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "payload": self.payload,
            "input_message_id": self.input_message_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class FlowV2SessionTimeline:
    """Builds the complete deterministic timeline for one Runtime V2 session."""

    def __init__(self, *, event_store: FlowV2EventStore | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()

    def build(self, db, *, tenant_id: UUID, session_id: UUID) -> tuple[TimelineEntry, ...]:
        events = self.event_store.list_for_session(db, tenant_id=tenant_id, session_id=session_id)
        return self.from_events(events)

    def from_events(self, events: list[Any] | tuple[Any, ...]) -> tuple[TimelineEntry, ...]:
        return tuple(self._entry(event) for event in sorted(events, key=self._event_index))

    @classmethod
    def _entry(cls, event: Any) -> TimelineEntry:
        payload = cls._get(event, "payload", {})
        return TimelineEntry(
            event_index=int(cls._get(event, "event_index", 0) or 0),
            event_type=str(cls._get(event, "event_type", "")),
            node_id=cls._get(event, "node_id", None),
            payload=payload if isinstance(payload, dict) else {},
            input_message_id=cls._get(event, "input_message_id", None),
            created_at=cls._get(event, "created_at", None),
        )

    @classmethod
    def _event_index(cls, event: Any) -> int:
        return int(cls._get(event, "event_index", 0) or 0)

    @staticmethod
    def _get(event: Any, key: str, default: Any = None) -> Any:
        if isinstance(event, dict):
            return event.get(key, default)
        return getattr(event, key, default)
