from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.inspector.session_replay import FlowV2SessionReplay
from app.flow_v2.models import FlowV2Session


@dataclass(frozen=True)
class ExecutionInspection:
    flow_version_id: UUID | None
    current_node_id: str | None
    status: str | None
    last_event: dict[str, Any] | None
    last_action: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "flow_version_id": str(self.flow_version_id) if self.flow_version_id else None,
            "current_node_id": self.current_node_id,
            "status": self.status,
            "last_event": self.last_event,
            "last_action": self.last_action,
        }


class FlowV2ExecutionInspector:
    """Read-only current execution view backed by the append-only V2 event stream."""

    def __init__(self, *, event_store: FlowV2EventStore | None = None, replay: FlowV2SessionReplay | None = None) -> None:
        self.event_store = event_store or FlowV2EventStore()
        self.replay_service = replay or FlowV2SessionReplay(event_store=self.event_store)

    def inspect(self, db, *, tenant_id: UUID, session_id: UUID) -> ExecutionInspection:
        session = db.execute(
            select(FlowV2Session).where(FlowV2Session.tenant_id == tenant_id, FlowV2Session.id == session_id)
        ).scalar_one_or_none()
        replay = self.replay_service.replay(db, tenant_id=tenant_id, session_id=session_id)
        return ExecutionInspection(
            flow_version_id=getattr(session, "flow_version_id", None) or replay.flow_version_id,
            current_node_id=getattr(session, "current_node_id", None) or replay.current_node_id,
            status=str(getattr(session, "status", "") or replay.status),
            last_event=replay.last_event,
            last_action=replay.last_action,
        )

    def inspect_events(self, events: list[Any] | tuple[Any, ...]) -> ExecutionInspection:
        replay = self.replay_service.from_events(events)
        return ExecutionInspection(
            flow_version_id=replay.flow_version_id,
            current_node_id=replay.current_node_id,
            status=replay.status,
            last_event=replay.last_event,
            last_action=replay.last_action,
        )
