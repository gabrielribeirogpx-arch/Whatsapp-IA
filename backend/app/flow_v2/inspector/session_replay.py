from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.inspector.session_timeline import FlowV2SessionTimeline, TimelineEntry

_ACTION_EVENTS = {
    str(FlowV2EventType.MESSAGE_SENT),
    str(FlowV2EventType.CHOICE_SHOWN),
    str(FlowV2EventType.CHOICE_SELECTED),
    str(FlowV2EventType.DELAY_SCHEDULED),
    str(FlowV2EventType.DELAY_RESUMED),
    str(FlowV2EventType.CONDITION_EVALUATED),
    str(FlowV2EventType.OUTPUT_EMITTED),
}


@dataclass(frozen=True)
class ReplayedSession:
    session_id: UUID | None
    flow_version_id: UUID | None
    current_node_id: str | None
    status: str
    last_event: dict[str, Any] | None
    last_action: dict[str, Any] | None
    timeline: tuple[TimelineEntry, ...]
    visited_node_ids: tuple[str, ...] = field(default_factory=tuple)
    messages_sent: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id) if self.session_id else None,
            "flow_version_id": str(self.flow_version_id) if self.flow_version_id else None,
            "current_node_id": self.current_node_id,
            "status": self.status,
            "last_event": self.last_event,
            "last_action": self.last_action,
            "timeline": [entry.as_dict() for entry in self.timeline],
            "visited_node_ids": list(self.visited_node_ids),
            "messages_sent": list(self.messages_sent),
        }


class FlowV2SessionReplay:
    """Replays a Runtime V2 session exclusively from flow_v2_events."""

    def __init__(self, *, event_store: FlowV2EventStore | None = None, timeline: FlowV2SessionTimeline | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()
        self.timeline = timeline or FlowV2SessionTimeline(event_store=self.event_store)

    def replay(self, db, *, tenant_id: UUID, session_id: UUID) -> ReplayedSession:
        events = self.event_store.list_for_session(db, tenant_id=tenant_id, session_id=session_id)
        return self.from_events(events, session_id=session_id)

    def from_events(self, events: list[Any] | tuple[Any, ...], *, session_id: UUID | None = None) -> ReplayedSession:
        timeline = self.timeline.from_events(events)
        flow_version_id = self._first(events, "flow_version_id")
        if session_id is None:
            session_id = self._first(events, "session_id")

        status = str(FlowV2SessionStatus.RUNNING)
        current_node_id: str | None = None
        visited: list[str] = []
        messages: list[dict[str, Any]] = []
        last_action: dict[str, Any] | None = None

        for entry in timeline:
            if entry.node_id:
                current_node_id = entry.node_id
            if entry.event_type == str(FlowV2EventType.SESSION_STARTED):
                status = str(FlowV2SessionStatus.RUNNING)
                current_node_id = entry.payload.get("start_node_id") or current_node_id
            elif entry.event_type == str(FlowV2EventType.NODE_ENTERED):
                if entry.node_id and entry.node_id not in visited:
                    visited.append(entry.node_id)
            elif entry.event_type == str(FlowV2EventType.TRANSITION_SELECTED):
                current_node_id = entry.payload.get("target_node_id") or current_node_id
            elif entry.event_type == str(FlowV2EventType.SESSION_WAITING):
                status = str(FlowV2SessionStatus.WAITING)
            elif entry.event_type == str(FlowV2EventType.SESSION_COMPLETED):
                status = str(FlowV2SessionStatus.COMPLETED)
            elif entry.event_type == str(FlowV2EventType.SESSION_FAILED):
                status = str(FlowV2SessionStatus.FAILED)

            if entry.event_type == str(FlowV2EventType.MESSAGE_SENT):
                messages.append(entry.payload)
            if entry.event_type in _ACTION_EVENTS:
                last_action = entry.as_dict()

        last_event = timeline[-1].as_dict() if timeline else None
        return ReplayedSession(
            session_id=session_id,
            flow_version_id=flow_version_id,
            current_node_id=current_node_id,
            status=status,
            last_event=last_event,
            last_action=last_action,
            timeline=timeline,
            visited_node_ids=tuple(visited),
            messages_sent=tuple(messages),
        )

    @staticmethod
    def _first(events: list[Any] | tuple[Any, ...], attr: str) -> Any:
        for event in events:
            value = event.get(attr) if isinstance(event, dict) else getattr(event, attr, None)
            if value is not None:
                return value
        return None
