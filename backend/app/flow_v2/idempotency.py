from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.flow_v2.models import FlowV2IdempotencyKey


@dataclass(frozen=True)
class IdempotencyDecision:
    key: str | None
    event_kind: str
    is_duplicate: bool
    record: Any | None = None


class FlowV2IdempotencyStore:
    """Persistent idempotency guard for every Runtime V2 ingress signal.

    Keys are scoped by tenant and event kind so webhook, choice and delay signals
    can be retried safely without re-executing nodes or re-sending actions.
    """

    def __init__(self) -> None:
        self._memory_keys: set[tuple[str, str, str]] = set()

    def reserve_once(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        event_kind: str,
        key: str | None,
        session_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IdempotencyDecision:
        if not key:
            return IdempotencyDecision(key=None, event_kind=event_kind, is_duplicate=False)

        if not hasattr(db, "execute") or not hasattr(db, "add"):
            memory_key = (str(tenant_id), event_kind, key)
            if memory_key in self._memory_keys:
                return IdempotencyDecision(key=key, event_kind=event_kind, is_duplicate=True)
            self._memory_keys.add(memory_key)
            return IdempotencyDecision(key=key, event_kind=event_kind, is_duplicate=False)

        existing = db.execute(
            select(FlowV2IdempotencyKey).where(
                FlowV2IdempotencyKey.tenant_id == tenant_id,
                FlowV2IdempotencyKey.event_kind == event_kind,
                FlowV2IdempotencyKey.idempotency_key == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return IdempotencyDecision(key=key, event_kind=event_kind, is_duplicate=True, record=existing)

        record = FlowV2IdempotencyKey(
            tenant_id=tenant_id,
            event_kind=event_kind,
            idempotency_key=key,
            session_id=session_id,
            payload=metadata or {},
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            if hasattr(db, "rollback"):
                db.rollback()
            existing = db.execute(
                select(FlowV2IdempotencyKey).where(
                    FlowV2IdempotencyKey.tenant_id == tenant_id,
                    FlowV2IdempotencyKey.event_kind == event_kind,
                    FlowV2IdempotencyKey.idempotency_key == key,
                )
            ).scalar_one_or_none()
            return IdempotencyDecision(key=key, event_kind=event_kind, is_duplicate=True, record=existing)
        return IdempotencyDecision(key=key, event_kind=event_kind, is_duplicate=False, record=record)

    def mark_session(self, db: Session, *, decision: IdempotencyDecision, session_id: UUID) -> None:
        record = decision.record
        if record is None or decision.is_duplicate:
            return
        if hasattr(record, "session_id"):
            record.session_id = session_id
            record.processed_at = datetime.utcnow()
            db.add(record)


def resolve_idempotency_key(*, input_message_id: str | None = None, metadata: dict[str, Any] | None = None) -> str | None:
    metadata = metadata or {}
    for field in ("event_id", "message_id", "webhook_id", "delay_job_id", "choice_id"):
        value = metadata.get(field)
        if value:
            return str(value)
    return input_message_id


def resolve_event_kind(*, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    raw = metadata.get("event_type") or metadata.get("kind") or metadata.get("source") or "webhook"
    value = str(raw)
    if "DELAY" in value.upper() or "delay" in value.lower():
        return "delay"
    if "CHOICE" in value.upper() or "choice" in value.lower():
        return "choice"
    return "webhook"
