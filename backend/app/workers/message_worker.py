from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Message
from app.models.flow_session import FINAL_SESSION_STATUSES, FlowSession
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.contact_event_service import register_contact_event
from app.services.conversation_service import get_or_create_conversation
from app.services.idempotency_service import register_processed_message
from app.services.lead_auto_service import ensure_whatsapp_lead_for_inbound
from app.services.message_router import handle_incoming_message
from app.services.message_service import normalize_meta_message
from app.core.redis_client import get_redis_client
from app.services.tenant_service import resolve_tenant_by_phone_number_id

logger = logging.getLogger(__name__)


def _persist_interactive_reply_context(db, session: FlowSession | None, parsed: dict[str, Any]) -> None:
    if not session:
        return
    interactive_type = str(parsed.get("interactive_type") or "").strip()
    selected_row_id = str(parsed.get("selected_row_id") or parsed.get("interactive_reply_id") or "").strip()
    selected_title = str(parsed.get("selected_title") or parsed.get("interactive_reply_title") or "").strip()
    if interactive_type != "list_reply" or not selected_row_id:
        return
    session.context = {
        **(session.context or {}),
        "last_interactive_type": interactive_type,
        "last_interactive_list_reply_id": selected_row_id,
        "last_interactive_list_reply_title": selected_title,
        "selected_row_id": selected_row_id,
        "selected_title": selected_title,
    }
    db.add(session)
    logger.info(
        "[CHOICE LIST RESPONSE] session_id=%s selected_row_id=%s selected_title=%s source=message_worker",
        session.id,
        selected_row_id,
        selected_title,
    )



DEDUP_TTL_SECONDS = 600
FLOW_LOCK_TTL_SECONDS = 15


def _extract_whatsapp_message_id(payload: dict[str, Any], parsed: dict[str, Any] | None) -> str:
    candidates = [
        (parsed or {}).get("message_id"),
        payload.get("message_id"),
        payload.get("wamid"),
        payload.get("id"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _release_session_lock(redis_client: Any, lock_key: str, lock_token: str) -> None:
    try:
        current = redis_client.get(lock_key)
        if current == lock_token:
            redis_client.delete(lock_key)
    except Exception:
        logger.warning("event=incoming_worker_lock_release_warning lock_key=%s", lock_key, exc_info=True)

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

    whatsapp_message_id = _extract_whatsapp_message_id(payload, parsed)
    correlation_id = whatsapp_message_id or str(parsed.get("message_id") or correlation_id)
    logger.info("event=incoming_worker_parsed correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_parse type=text", correlation_id, "n/a", parsed.get("phone") or "n/a", payload.get("job_id") or "n/a")

    redis_client = get_redis_client()
    dedup_key = f"wa:processed:{whatsapp_message_id}" if whatsapp_message_id else ""
    if dedup_key:
        was_set = bool(redis_client.set(dedup_key, "1", ex=DEDUP_TTL_SECONDS, nx=True))
        if not was_set:
            logger.info("[DUPLICATE MESSAGE BLOCKED] message_id=%s", whatsapp_message_id)
            return

    db = SessionLocal()
    lock_key = ""
    lock_token = ""
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

        lock_key = f"flow:lock:{tenant.id}:{str(parsed.get('phone') or '').strip()}"
        lock_token = str(uuid.uuid4())
        acquired_lock = bool(redis_client.set(lock_key, lock_token, ex=FLOW_LOCK_TTL_SECONDS, nx=True))
        if not acquired_lock:
            logger.info("[FLOW LOCKED SKIP] tenant_id=%s phone=%s", tenant.id, parsed.get("phone") or "n/a")
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

        phone = str(parsed.get("phone") or "").strip()
        text = str(parsed.get("text") or "")
        payload_profile_name = (
            str(((payload.get("contacts") or [{}])[0].get("profile") or {}).get("name") or "").strip()
            if isinstance(payload.get("contacts"), list)
            else ""
        )
        name = str(parsed.get("name") or "").strip() or payload_profile_name or phone

        try:
            print(f"[CONTACT UPSERT START] tenant_id={tenant.id} phone={phone} name={name}")
            contact = upsert_contact_for_phone(
                db=db,
                tenant_id=tenant.id,
                phone=phone,
                name=name,
                source="whatsapp",
            )
            db.flush()
            db.commit()
            print(f"[CONTACT UPSERT COMMIT OK] contact_id={getattr(contact, 'id', None)} phone={phone}")
        except Exception as exc:
            db.rollback()
            print(f"[CONTACT UPSERT ERROR] tenant_id={tenant.id} phone={phone} error={type(exc).__name__}: {str(exc)[:300]}")
            contact = None
        conversation, _ = get_or_create_conversation(
            db,
            tenant_id=tenant.id,
            phone=(contact.phone if contact else phone),
            contact_id=contact.id if contact else None,
            message=text,
        )
        ensure_conversation_contact_link(conversation, contact)
        lead_phone = contact.phone if contact else phone
        contact_id = contact.id if contact else None
        try:
            ensure_whatsapp_lead_for_inbound(
                db=db,
                tenant_id=tenant.id,
                phone=lead_phone,
                contact=contact,
                conversation=conversation,
                name=name,
                message_text=text,
                conversation_created=False,
            )
        except Exception:
            logger.warning(
                "[FLOW CONTINUING AFTER LEAD RECOVERY] tenant_id=%s phone=%s reason=lead_creation_failed",
                tenant.id,
                lead_phone,
                exc_info=True,
            )
            if db.in_transaction():
                db.rollback()
            conversation, _ = get_or_create_conversation(
                db,
                tenant_id=tenant.id,
                phone=lead_phone,
                contact_id=contact_id,
                message=text,
            )
            ensure_conversation_contact_link(conversation, contact)
        logger.info(
            "event=incoming_worker_entities_ready correlation_id=%s tenant_id=%s contact_id=%s conversation_id=%s",
            correlation_id,
            tenant.id,
            contact.id if contact else "n/a",
            conversation.id,
        )

        inbound = Message(
            conversation_id=conversation.id,
            tenant_id=tenant.id,
            text=text,
            from_me=False,
            created_at=datetime.utcnow(),
        )
        db.add(inbound)
        db.flush()
        if contact:
            register_contact_event(db, tenant_id=tenant.id, contact_id=contact.id, event_type="message_received", title="Mensagem recebida", description=text, contact=contact)
            lower_text = (text or "").lower()
            keyword_tags = [("suporte", "suporte"), ("preço", "interesse_preco"), ("comprar", "quente"), ("problema", "risco")]
            tags = list(contact.tags_json or [])
            for keyword, tag in keyword_tags:
                if keyword in lower_text and tag not in tags:
                    tags.append(tag)
            contact.tags_json = tags
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
            phone=(contact.phone if contact else phone),
            contact_id=contact.id if contact else None,
        )

        if persisted_message and persisted_conversation:
            active_session = (
                db.query(FlowSession)
                .filter(
                    FlowSession.tenant_id == tenant.id,
                    FlowSession.conversation_id == str(persisted_conversation.id),
                )
                .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
                .first()
            )
            if active_session and (active_session.status or "").lower() not in FINAL_SESSION_STATUSES:
                _persist_interactive_reply_context(db, active_session, parsed)
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
        if lock_key and lock_token:
            _release_session_lock(redis_client, lock_key, lock_token)
        db.close()


    logger.info("event=incoming_worker_done correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_done", correlation_id, payload.get("tenant_id") or "n/a", parsed.get("phone") if parsed else payload.get("phone") or "n/a", payload.get("job_id") or "n/a")
