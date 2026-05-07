from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Message
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.conversation_service import get_or_create_conversation
from app.services.idempotency_service import register_processed_message
from app.services.message_router import handle_incoming_message
from app.services.message_service import normalize_meta_message
from app.services.tenant_service import resolve_tenant_by_phone_number_id

logger = logging.getLogger(__name__)


def _pick_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    normalized = normalize_meta_message(payload)
    if normalized:
        return normalized[0]

    if payload.get("phone") and payload.get("text"):
        return {
            "phone": str(payload.get("phone") or "").strip(),
            "text": str(payload.get("text") or "").strip(),
            "message_id": str(payload.get("message_id") or "").strip(),
            "name": str(payload.get("name") or "Cliente").strip(),
            "phone_number_id": str(payload.get("phone_number_id") or "").strip(),
        }
    return None


def process_incoming_message(payload: dict[str, Any]) -> None:
    raw_correlation = payload.get("correlation_id") or payload.get("message_id")
    correlation_id = str(raw_correlation or "n/a")
    logger.info("event=incoming_worker_start correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_start", correlation_id, "n/a", payload.get("phone") or "n/a", payload.get("job_id") or "n/a")

    parsed = _pick_message(payload)
    if not parsed:
        logger.warning("event=incoming_worker_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_parse reason=no_supported_message", correlation_id, "n/a", payload.get("phone") or "n/a", payload.get("job_id") or "n/a")
        return

    correlation_id = str(parsed.get("message_id") or correlation_id)
    logger.info("event=incoming_worker_parsed correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_parse type=text", correlation_id, "n/a", parsed.get("phone") or "n/a", payload.get("job_id") or "n/a")

    db = SessionLocal()
    try:
        phone_number_id = str(parsed.get("phone_number_id") or "").strip()
        tenant = resolve_tenant_by_phone_number_id(db, phone_number_id)
        if not tenant:
            logger.warning(
                "event=incoming_worker_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_tenant reason=tenant_not_found phone_number_id=%s",
                correlation_id,
                "n/a",
                parsed.get("phone") or "n/a",
                payload.get("job_id") or "n/a",
                phone_number_id,
            )
            return

        logger.info(
            "event=incoming_worker_tenant_resolved correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_tenant",
            correlation_id,
            tenant.id,
            parsed.get("phone") or "n/a",
            payload.get("job_id") or "n/a",
        )

        is_new = register_processed_message(db=db, tenant_id=tenant.id, message_id=correlation_id)
        if not is_new:
            logger.info("event=incoming_worker_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_dedup reason=duplicate", correlation_id, tenant.id, parsed.get("phone") or "n/a", payload.get("job_id") or "n/a")
            db.commit()
            return

        contact = upsert_contact_for_phone(
            db,
            tenant_id=tenant.id,
            phone=str(parsed.get("phone") or ""),
            name=str(parsed.get("name") or "").strip() or None,
        )
        conversation, _ = get_or_create_conversation(
            db,
            tenant_id=tenant.id,
            phone=contact.phone,
            contact_id=contact.id,
            message=str(parsed.get("text") or ""),
        )
        ensure_conversation_contact_link(conversation, contact)
        logger.info(
            "event=incoming_worker_entities_ready correlation_id=%s tenant_id=%s contact_id=%s conversation_id=%s",
            correlation_id,
            tenant.id,
            contact.id,
            conversation.id,
        )

        inbound = Message(
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            text=str(parsed.get("text") or ""),
            from_me=False,
            created_at=datetime.utcnow(),
        )
        db.add(inbound)
        db.flush()
        db.refresh(inbound)
        logger.info(
            "event=incoming_worker_message_persisted correlation_id=%s message_pk=%s",
            correlation_id,
            inbound.id,
        )

        persisted_message = db.execute(select(Message).where(Message.id == inbound.id)).scalars().first()
        persisted_conversation, _ = get_or_create_conversation(
            db,
            tenant_id=tenant.id,
            phone=contact.phone,
            contact_id=contact.id,
        )

        if persisted_message and persisted_conversation:
            try:
                handle_incoming_message(db=db, message=persisted_message, conversation=persisted_conversation)
            except Exception:
                logger.warning(
                    "event=incoming_worker_tracking_warning correlation_id=%s tenant_id=%s stage=incoming_worker_flow reason=tracking_failed",
                    correlation_id,
                    tenant.id,
                    exc_info=True,
                )
        logger.info("event=incoming_worker_flow_executed correlation_id=%s", correlation_id)

        db.commit()
    except Exception:
        if db.in_transaction():
            db.rollback()
        raise
    finally:
        db.close()

    logger.info("event=incoming_worker_done correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_done", correlation_id, payload.get("tenant_id") or "n/a", parsed.get("phone") if parsed else payload.get("phone") or "n/a", payload.get("job_id") or "n/a")
