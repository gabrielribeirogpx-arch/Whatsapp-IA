from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.flow_event import FlowEvent

logger = logging.getLogger(__name__)


FLOW_START = "FLOW_START"
FLOW_SEND = "FLOW_SEND"
FLOW_MATCH = "FLOW_MATCH"
FALLBACK = "FALLBACK"
FLOW_FINISH = "FLOW_FINISH"


VALID_EVENT_TYPES = {FLOW_START, FLOW_SEND, FLOW_MATCH, FALLBACK, FLOW_FINISH}


def get_flow_analytics(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
) -> dict[str, int]:
    event_counts_stmt = (
        select(FlowEvent.event_type, func.count(FlowEvent.id))
        .where(
            FlowEvent.tenant_id == tenant_id,
            FlowEvent.flow_id == flow_id,
            FlowEvent.event_type.in_({FLOW_START, FLOW_SEND, FLOW_FINISH}),
        )
        .group_by(FlowEvent.event_type)
    )
    rows = db.execute(event_counts_stmt).all()
    counts_by_event = {event_type: total for event_type, total in rows}

    return {
        "entries": counts_by_event.get(FLOW_START, 0),
        "messages_sent": counts_by_event.get(FLOW_SEND, 0),
        "finalizations": counts_by_event.get(FLOW_FINISH, 0),
    }


def record_flow_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_id: uuid.UUID | None,
    node_id: uuid.UUID | None,
    event_type: str,
) -> None:
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("event=flow_event_skip reason=invalid_type event_type=%s", event_type)
        return

    db.add(
        FlowEvent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            flow_id=flow_id,
            node_id=node_id,
            event_type=event_type,
        )
    )
    logger.info(
        "event=flow_event_recorded tenant_id=%s conversation_id=%s flow_id=%s node_id=%s event_type=%s",
        tenant_id,
        conversation_id,
        flow_id,
        node_id,
        event_type,
    )
