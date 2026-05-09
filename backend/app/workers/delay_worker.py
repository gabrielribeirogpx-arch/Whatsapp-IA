from __future__ import annotations

import logging
import uuid
from sqlalchemy.orm import Session

from app.models import Conversation
from app.models.flow_session import FlowSession
from app.services.flow_engine_service import process_flow_engine

logger = logging.getLogger(__name__)


def resume_after_delay(db: Session, tenant_id: uuid.UUID, phone: str, delay_node_id: uuid.UUID | str | None, next_node_id: uuid.UUID | str | None) -> None:
    logger.info("[DELAY RESUME] delay_node_id=%s next_node_id=%s", delay_node_id, next_node_id)
    flow_id = None
    flow_session_id = None
    flow_version_id = None
    expected_current_node_id = None

    if isinstance(delay_node_id, dict):
        payload = delay_node_id
        phone = str(payload.get("phone") or payload.get("user_identifier") or phone or "")
        next_node_id = payload.get("next_node_id")
        delay_node_id = payload.get("delay_node_id")
        flow_id = payload.get("flow_id")
        flow_session_id = payload.get("flow_session_id")
        flow_version_id = payload.get("flow_version_id")
        expected_current_node_id = payload.get("expected_current_node_id")
        tenant_id = uuid.UUID(str(payload.get("tenant_id"))) if payload.get("tenant_id") else tenant_id

    session = None
    if flow_id:
        session = (
            db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.user_identifier == phone,
                FlowSession.flow_id == uuid.UUID(str(flow_id)),
            )
            .order_by(FlowSession.updated_at.desc())
            .first()
        )

    if session:
        session_current_node = str(session.current_node_id or "")
        expected_node = str(expected_current_node_id or "")
        delay_node = str(delay_node_id or "")
        status = str(session.status or "").lower()
        stale_reason = None
        if flow_session_id and str(session.id) != str(flow_session_id):
            stale_reason = "session_id_mismatch"
        elif status not in {"running", "active"}:
            stale_reason = "session_not_active"
        elif flow_version_id and str(session.flow_version_id) != str(flow_version_id):
            stale_reason = "flow_version_mismatch"
        elif session_current_node not in {expected_node, delay_node}:
            stale_reason = "current_node_mismatch"

        if stale_reason:
            logger.info(
                "[STALE DELAY DROPPED] reason=%s session_id=%s session_status=%s session_current_node_id=%s expected_current_node_id=%s delay_node_id=%s next_node_id=%s",
                stale_reason,
                getattr(session, "id", None),
                getattr(session, "status", None),
                getattr(session, "current_node_id", None),
                expected_current_node_id,
                delay_node_id,
                next_node_id,
            )
            return
    elif flow_id:
        logger.info(
            "[STALE DELAY DROPPED] reason=%s session_id=%s session_status=%s session_current_node_id=%s expected_current_node_id=%s delay_node_id=%s next_node_id=%s",
            "session_not_found",
            flow_session_id,
            None,
            None,
            expected_current_node_id,
            delay_node_id,
            next_node_id,
        )
        return

    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone).first()
    if conversation and isinstance(conversation.context, dict):
        conversation.context["flow_current_node_id"] = str(next_node_id) if next_node_id else None
        db.add(conversation)
        db.commit()
    process_flow_engine(db=db, tenant_id=tenant_id, phone=phone, message_text="", force_node=(uuid.UUID(str(next_node_id)) if next_node_id else None))
