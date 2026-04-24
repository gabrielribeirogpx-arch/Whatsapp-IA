from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.flow_event import FlowEvent

logger = logging.getLogger(__name__)


FLOW_START = "FLOW_START"
FLOW_SEND = "FLOW_SEND"
FLOW_MATCH = "FLOW_MATCH"
FALLBACK = "FALLBACK"


VALID_EVENT_TYPES = {FLOW_START, FLOW_SEND, FLOW_MATCH, FALLBACK}


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
