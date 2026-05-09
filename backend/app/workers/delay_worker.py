from __future__ import annotations

import logging
import uuid
from sqlalchemy.orm import Session

from app.models import Conversation
from app.services.flow_engine_service import process_flow_engine

logger = logging.getLogger(__name__)


def resume_after_delay(db: Session, tenant_id: uuid.UUID, phone: str, delay_node_id: uuid.UUID | str | None, next_node_id: uuid.UUID | str | None) -> None:
    logger.info("[DELAY RESUME] delay_node_id=%s next_node_id=%s", delay_node_id, next_node_id)
    conversation = db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone).first()
    if conversation and isinstance(conversation.context, dict):
        conversation.context["flow_current_node_id"] = str(next_node_id) if next_node_id else None
        db.add(conversation)
        db.commit()
    process_flow_engine(db=db, tenant_id=tenant_id, phone=phone, message_text="", force_node=(uuid.UUID(str(next_node_id)) if next_node_id else None))
