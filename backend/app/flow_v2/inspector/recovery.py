from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.inspector.session_replay import FlowV2SessionReplay


@dataclass(frozen=True)
class RecoveredSession:
    session_id: UUID | None
    flow_version_id: UUID | None
    current_node_id: str | None
    status: str
    last_event_index: int
    state: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id) if self.session_id else None,
            "flow_version_id": str(self.flow_version_id) if self.flow_version_id else None,
            "current_node_id": self.current_node_id,
            "status": self.status,
            "last_event_index": self.last_event_index,
            "state": self.state,
        }


class FlowV2RecoveryEngine:
    """Reconstructs the minimal Runtime V2 session pointer from events only."""

    def __init__(self, *, event_store: FlowV2EventStore | None = None, replay: FlowV2SessionReplay | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()
        self.replay_service = replay or FlowV2SessionReplay(event_store=self.event_store)

    def recover(self, db, *, tenant_id: UUID, session_id: UUID) -> RecoveredSession:
        events = self.event_store.list_for_session(db, tenant_id=tenant_id, session_id=session_id)
        return self.from_events(events, session_id=session_id)

    def from_events(self, events: list[Any] | tuple[Any, ...], *, session_id: UUID | None = None) -> RecoveredSession:
        replay = self.replay_service.from_events(events, session_id=session_id)
        last_event_index = replay.timeline[-1].event_index if replay.timeline else 0
        state = {
            "last_event": replay.last_event,
            "last_action": replay.last_action,
            "visited_node_ids": list(replay.visited_node_ids),
            "messages_sent": list(replay.messages_sent),
            "event_count": len(replay.timeline),
        }
        return RecoveredSession(
            session_id=replay.session_id,
            flow_version_id=replay.flow_version_id,
            current_node_id=replay.current_node_id,
            status=replay.status,
            last_event_index=last_event_index,
            state=state,
        )
