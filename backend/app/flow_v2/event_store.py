from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType
from app.flow_v2.models import FlowV2Event, FlowV2Session


class FlowV2EventStore:
    """Append-only event store for Runtime V2.

    The session row owns only the current stream cursor. Every state transition
    must be represented here before the session pointer is advanced.
    """

    def append(
        self,
        db: Session,
        *,
        session: FlowV2Session,
        event_type: FlowV2EventType,
        payload: dict[str, Any] | None = None,
        node_id: str | None = None,
        input_message_id: str | None = None,
    ) -> FlowV2Event:
        next_index = session.last_event_index + 1
        event = FlowV2Event(
            tenant_id=session.tenant_id,
            session_id=session.id,
            flow_version_id=session.flow_version_id,
            event_index=next_index,
            event_type=str(event_type),
            node_id=node_id,
            input_message_id=input_message_id,
            payload=payload or {},
        )
        db.add(event)
        session.last_event_index = next_index
        return event

    def list_for_session(self, db: Session, *, tenant_id: UUID, session_id: UUID) -> list[FlowV2Event]:
        return list(
            db.execute(
                select(FlowV2Event)
                .where(FlowV2Event.tenant_id == tenant_id, FlowV2Event.session_id == session_id)
                .order_by(FlowV2Event.event_index.asc())
            ).scalars()
        )
