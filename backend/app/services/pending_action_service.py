from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.pending_action import PendingAction

logger = logging.getLogger(__name__)

class PendingActionType(str, Enum):
    CALENDAR_CREATE_CONFIRMATION = "CALENDAR_CREATE_CONFIRMATION"
    CALENDAR_DELETE_CONFIRMATION = "CALENDAR_DELETE_CONFIRMATION"
    EMAIL_SEND_CONFIRMATION = "EMAIL_SEND_CONFIRMATION"
    LEAD_DELETE_CONFIRMATION = "LEAD_DELETE_CONFIRMATION"
    PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    CRM_STAGE_MOVE_CONFIRMATION = "CRM_STAGE_MOVE_CONFIRMATION"


class PendingActionDecision(str, Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


CALENDAR_CREATE_CONFIRMATION = PendingActionType.CALENDAR_CREATE_CONFIRMATION.value
CALENDAR_DELETE_CONFIRMATION = PendingActionType.CALENDAR_DELETE_CONFIRMATION.value
EMAIL_SEND_CONFIRMATION = PendingActionType.EMAIL_SEND_CONFIRMATION.value
LEAD_DELETE_CONFIRMATION = PendingActionType.LEAD_DELETE_CONFIRMATION.value
PAYMENT_CONFIRMATION = PendingActionType.PAYMENT_CONFIRMATION.value
ORDER_CONFIRMATION = PendingActionType.ORDER_CONFIRMATION.value
CRM_STAGE_MOVE_CONFIRMATION = PendingActionType.CRM_STAGE_MOVE_CONFIRMATION.value

def _normalize_decision_text(text: str) -> str:
    import unicodedata

    normalized = "".join(ch for ch in unicodedata.normalize("NFD", str(text or "").lower().strip()) if unicodedata.category(ch) != "Mn")
    return " ".join(normalized.strip(" .,!?:;\n\t").split())


def detect_pending_action_decision(text: str) -> str:
    normalized = _normalize_decision_text(text)
    confirm_phrases = {"sim", "ok", "confirmar", "confirmo", "pode criar", "pode sim", "crie mesmo assim", "pode fazer", "autorizado", "yes"}
    cancel_phrases = {"nao", "cancelar", "cancela", "nao precisa", "deixa pra la", "desiste", "no"}
    if normalized in confirm_phrases:
        return PendingActionDecision.CONFIRM.value
    if normalized in cancel_phrases:
        return PendingActionDecision.CANCEL.value
    return PendingActionDecision.UNKNOWN.value


def normalize_calendar_conflicting_event(event: dict[str, Any]) -> dict[str, Any]:
    allowed = ("summary", "title", "name", "description", "id", "start", "end")
    return {key: event.get(key) for key in allowed if key in event}


def _calendar_conflict_display_name(event: dict[str, Any]) -> str:
    for key in ("summary", "title", "name"):
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return "compromisso"


def format_pending_calendar_create_conflict_message(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary") or payload.get("title") or payload.get("name") or "compromisso").strip() or "compromisso"
    conflicts_raw = payload.get("conflicting_events") if isinstance(payload, dict) else []
    conflicts = [normalize_calendar_conflicting_event(item) for item in conflicts_raw if isinstance(item, dict)] if isinstance(conflicts_raw, list) else []
    if not conflicts:
        return f'Você já possui um compromisso nesse horário. Deseja criar "{summary}" mesmo assim?'
    start_raw = str(payload.get("start_time") or payload.get("start") or "").strip()
    try:
        time_label = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        time_label = start_raw[11:16] if len(start_raw) >= 16 else "nesse horário"
    date_label = str(payload.get("date_label") or "amanhã").strip() or "amanhã"
    names = [_calendar_conflict_display_name(event) for event in conflicts]
    bullet_list = "\n".join(f"• {name}" for name in names)
    if len(names) == 1:
        message = f'Você já possui um compromisso {date_label} às {time_label}:\n\n{bullet_list}\n\nDeseja criar "{summary}" mesmo assim?'
    else:
        message = f'Já existem {len(names)} compromissos {date_label} às {time_label}:\n\n{bullet_list}\n\nDeseja criar "{summary}" mesmo assim?'
    logger.info("event=%s %s", "PENDING_ACTION_CONFLICT_MESSAGE_FORMATTED", json.dumps({"action_type": CALENDAR_CREATE_CONFIRMATION}, ensure_ascii=False))
    return message


PendingActionHandler = Callable[..., str]


class PendingActionHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, PendingActionHandler] = {}

    def register(self, *, action_type: str | PendingActionType, handler: PendingActionHandler) -> None:
        key = action_type.value if isinstance(action_type, PendingActionType) else str(action_type)
        self._handlers[key] = handler

    def get(self, action_type: str | PendingActionType) -> PendingActionHandler | None:
        key = action_type.value if isinstance(action_type, PendingActionType) else str(action_type)
        return self._handlers.get(key)

    def handle(self, *, tenant_id: Any, conversation_id: Any, pending_action: Any, user_message: str, context: dict[str, Any]) -> str:
        action_type = str(getattr(pending_action, "action_type", "") or "")
        handler = self.get(action_type)
        pending_id = getattr(pending_action, "id", None)
        if handler is None:
            _log("PENDING_ACTION_HANDLER_MISSING", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id, decision=context.get("decision"))
            return "Não consegui confirmar essa ação agora. Tente novamente em instantes."
        _log("PENDING_ACTION_HANDLER_FOUND", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id, decision=context.get("decision"))
        _log("PENDING_ACTION_HANDLER_EXECUTE", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id, decision=context.get("decision"))
        response = handler(tenant_id=tenant_id, conversation_id=conversation_id, pending_action=pending_action, user_message=user_message, context=context)
        _log("PENDING_ACTION_HANDLER_RESULT", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id, decision=context.get("decision"))
        return response


DEFAULT_PENDING_ACTION_TTL_MINUTES = 15


def _log(event: str, *, tenant_id: Any, conversation_id: Any, action_type: str | None = None, pending_id: Any = None, decision: str | None = None) -> None:
    logger.info(
        "event=%s %s",
        event,
        json.dumps(
            {"tenant_id": str(tenant_id), "conversation_id": str(conversation_id), "action_type": action_type, "pending_id": str(pending_id) if pending_id else None, "decision": decision},
            ensure_ascii=False,
            default=str,
        ),
    )


class PendingActionService:
    def __init__(self, db: Session):
        self.db = db

    def _can_persist(self) -> bool:
        return hasattr(self.db, "query") and hasattr(self.db, "add")

    def save_pending_action(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        action_type: str,
        payload: dict[str, Any],
        session_id: uuid.UUID | None = None,
        external_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> PendingAction | None:
        if not self._can_persist():
            return None
        self.clear_pending_action(tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type)
        pending = PendingAction(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            session_id=session_id,
            external_user_id=external_user_id,
            action_type=action_type,
            payload_json=payload,
            metadata_json=metadata,
            expires_at=expires_at or (datetime.utcnow() + timedelta(minutes=DEFAULT_PENDING_ACTION_TTL_MINUTES)),
        )
        self.db.add(pending)
        self.db.flush()
        _log("PENDING_ACTION_SAVE", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending.id)
        return pending

    def get_pending_action(self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, action_type: str | None = None) -> PendingAction | None:
        if not self._can_persist():
            return None
        query = self.db.query(PendingAction).filter(
            PendingAction.tenant_id == tenant_id,
            PendingAction.conversation_id == conversation_id,
            PendingAction.consumed_at.is_(None),
        )
        if action_type:
            query = query.filter(PendingAction.action_type == action_type)
        pending = query.order_by(PendingAction.created_at.desc()).first()
        if pending is None:
            _log("PENDING_ACTION_NOT_FOUND", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type)
            return None
        if pending.expires_at <= datetime.utcnow():
            _log("PENDING_ACTION_EXPIRED", tenant_id=tenant_id, conversation_id=conversation_id, action_type=pending.action_type, pending_id=pending.id)
            self.clear_pending_action(tenant_id=tenant_id, conversation_id=conversation_id, pending_id=pending.id)
            return None
        _log("PENDING_ACTION_FOUND", tenant_id=tenant_id, conversation_id=conversation_id, action_type=pending.action_type, pending_id=pending.id)
        return pending

    def consume_pending_action(self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, pending_id: uuid.UUID | None = None, action_type: str | None = None) -> bool:
        pending = self._find(tenant_id=tenant_id, conversation_id=conversation_id, pending_id=pending_id, action_type=action_type)
        if pending is None:
            _log("PENDING_ACTION_NOT_FOUND", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id)
            return False
        pending.consumed_at = datetime.utcnow()
        self.db.flush()
        _log("PENDING_ACTION_CONSUME", tenant_id=tenant_id, conversation_id=conversation_id, action_type=pending.action_type, pending_id=pending.id)
        return True

    def cancel_pending_action(self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, pending_id: uuid.UUID | None = None, action_type: str | None = None) -> bool:
        pending = self._find(tenant_id=tenant_id, conversation_id=conversation_id, pending_id=pending_id, action_type=action_type)
        if pending is None:
            _log("PENDING_ACTION_NOT_FOUND", tenant_id=tenant_id, conversation_id=conversation_id, action_type=action_type, pending_id=pending_id)
            return False
        self.db.delete(pending)
        self.db.flush()
        _log("PENDING_ACTION_CANCEL", tenant_id=tenant_id, conversation_id=conversation_id, action_type=pending.action_type, pending_id=pending.id)
        return True

    def clear_pending_action(self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, pending_id: uuid.UUID | None = None, action_type: str | None = None) -> int:
        if not self._can_persist():
            return 0
        query = self.db.query(PendingAction).filter(PendingAction.tenant_id == tenant_id, PendingAction.conversation_id == conversation_id)
        if pending_id:
            query = query.filter(PendingAction.id == pending_id)
        if action_type:
            query = query.filter(PendingAction.action_type == action_type)
        count = query.delete(synchronize_session=False)
        self.db.flush()
        return int(count or 0)

    def cleanup_expired_actions(self, *, now: datetime | None = None) -> int:
        if not self._can_persist():
            return 0
        return int(self.db.query(PendingAction).filter(PendingAction.expires_at <= (now or datetime.utcnow())).delete(synchronize_session=False) or 0)

    def _find(self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, pending_id: uuid.UUID | None, action_type: str | None) -> PendingAction | None:
        if not self._can_persist():
            return None
        query = self.db.query(PendingAction).filter(PendingAction.tenant_id == tenant_id, PendingAction.conversation_id == conversation_id, PendingAction.consumed_at.is_(None))
        if pending_id:
            query = query.filter(PendingAction.id == pending_id)
        if action_type:
            query = query.filter(PendingAction.action_type == action_type)
        return query.order_by(PendingAction.created_at.desc()).first()
