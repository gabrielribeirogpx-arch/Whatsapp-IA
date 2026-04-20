from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models import ConversationLog


ALLOWED_MODES = {"human", "bot", "ai"}


def log_conversation_event(db: Session, data: Mapping[str, Any]) -> ConversationLog:
    mode = str(data.get("mode") or "human")
    if mode not in ALLOWED_MODES:
        mode = "human"

    log = ConversationLog(
        tenant_id=data["tenant_id"],
        conversation_id=data["conversation_id"],
        message=str(data.get("message") or ""),
        mode=mode,
        intent=data.get("intent"),
        matched_rule=data.get("matched_rule"),
        flow_step=data.get("flow_step"),
        used_fallback=bool(data.get("used_fallback", False)),
        response=data.get("response"),
    )
    db.add(log)
    return log
