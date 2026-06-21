from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.pending_action import PendingAction

logger = logging.getLogger(__name__)

CALENDAR_CREATE_CONFIRMATION = "CALENDAR_CREATE_CONFIRMATION"
CALENDAR_DELETE_CONFIRMATION = "CALENDAR_DELETE_CONFIRMATION"
EMAIL_SEND_CONFIRMATION = "EMAIL_SEND_CONFIRMATION"
LEAD_DELETE_CONFIRMATION = "LEAD_DELETE_CONFIRMATION"
PAYMENT_CONFIRMATION = "PAYMENT_CONFIRMATION"

DEFAULT_PENDING_ACTION_TTL_MINUTES = 15


def _log(event: str, *, tenant_id: Any, conversation_id: Any, action_type: str | None = None, pending_id: Any = None) -> None:
    logger.info(
        "event=%s %s",
        event,
        json.dumps(
            {"tenant_id": str(tenant_id), "conversation_id": str(conversation_id), "action_type": action_type, "pending_id": str(pending_id) if pending_id else None},
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
