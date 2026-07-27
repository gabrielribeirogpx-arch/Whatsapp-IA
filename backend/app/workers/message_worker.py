from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.services.job_queue_service import unwrap_job_envelope
from app.models import Message, TenantWhatsAppProvider
from app.models.flow_session import FINAL_SESSION_STATUSES, FlowSession, set_current_node_write_reason
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.contact_event_service import register_contact_event
from app.services.conversation_service import get_or_create_conversation
from app.services.idempotency_service import register_processed_message
from app.services.lead_auto_service import ensure_whatsapp_lead_for_inbound
from app.services.message_router import handle_incoming_message
from app.services.flow_runtime_selector import (
    FlowRuntimeSelector,
    bind_conversation_to_flow,
    resolve_flow_runtime,
    resolve_runtime_flow_for_conversation,
)
from app.services.message_service import normalize_meta_message
from app.core.redis_client import get_redis_client
from app.services.tenant_service import resolve_tenant_by_phone_number_id
from app.services.realtime_service import sse_broker
from app.schemas.chat import MessageOut

logger = logging.getLogger(__name__)


def _runtime_commit_sha() -> str:
    for env_name in (
        "WORKER_COMMIT",
        "API_COMMIT",
        "GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "HEROKU_SLUG_COMMIT",
        "SOURCE_VERSION",
        "COMMIT_SHA",
    ):
        commit = str(os.getenv(env_name) or "").strip()
        if commit:
            return commit

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"

    return completed.stdout.strip() or "unknown"


def _payload_shape(payload: dict[str, Any]) -> str:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return f"missing_or_invalid_entry type={type(entries).__name__}"
    message_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) if isinstance(entry.get("changes"), list) else []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            messages = value.get("messages")
            if isinstance(messages, list):
                message_count += len(messages)
    return f"entry_count={len(entries)} message_count={message_count}"


def _json_log_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(payload)


def _direct_message_debug_fields(payload: dict[str, Any]) -> dict[str, str]:
    interactive = payload.get("interactive") if isinstance(payload.get("interactive"), dict) else {}
    list_reply = interactive.get("list_reply") if isinstance(interactive.get("list_reply"), dict) else {}
    message_type = payload.get("type") or ("interactive" if payload.get("interactive_type") or payload.get("selected_row_id") or payload.get("interactive_reply_id") else "")
    interactive_type = payload.get("interactive_type") or interactive.get("type") or ("list_reply" if payload.get("selected_row_id") else "")
    return {
        "message_type": str(message_type or "").strip(),
        "interactive_type": str(interactive_type or "").strip(),
        "interactive_list_reply_id": str(list_reply.get("id") or payload.get("selected_row_id") or payload.get("interactive_reply_id") or "").strip(),
        "interactive_list_reply_title": str(list_reply.get("title") or payload.get("selected_title") or payload.get("interactive_reply_title") or "").strip(),
    }


def _log_direct_message_marker(marker: str, payload: dict[str, Any]) -> None:
    fields = _direct_message_debug_fields(payload)
    logger.info(
        "%s message.type=%s interactive.type=%s interactive.list_reply.id=%s interactive.list_reply.title=%s payload=%s source=message_worker_direct_payload",
        marker,
        fields["message_type"] or "n/a",
        fields["interactive_type"] or "n/a",
        fields["interactive_list_reply_id"] or "n/a",
        fields["interactive_list_reply_title"] or "n/a",
        _json_log_payload(payload),
    )


def _choice_log_context(session: FlowSession | None, selected_row_id: str = "", selected_title: str = "") -> dict[str, Any]:
    context = session.context if session and isinstance(getattr(session, "context", None), dict) else {}
    return {
        "session_id": getattr(session, "id", None),
        "node_id": getattr(session, "current_node_id", None) or context.get("choice_node_id"),
        "selected_row_id": selected_row_id or context.get("selected_row_id") or context.get("last_interactive_list_reply_id"),
        "selected_title": selected_title or context.get("selected_title") or context.get("last_interactive_list_reply_title"),
    }


def _log_choice_message_marker(marker: str, session: FlowSession | None, *, selected_row_id: str = "", selected_title: str = "", correlation_id: str = "n/a", reason: str = "n/a") -> None:
    data = _choice_log_context(session, selected_row_id, selected_title)
    logger.info(
        "%s session_id=%s node_id=%s selected_row_id=%s selected_title=%s worker_id=%s correlation_id=%s reason=%s source=message_worker",
        marker,
        data.get("session_id"),
        data.get("node_id"),
        data.get("selected_row_id"),
        data.get("selected_title"),
        _worker_id(),
        correlation_id,
        reason,
    )

def _worker_id() -> str:
    return str(os.getenv("WORKER_ID") or os.getenv("HOSTNAME") or os.getpid())


def _persist_interactive_reply_context(db, session: FlowSession | None, parsed: dict[str, Any], *, correlation_id: str = "n/a") -> None:
    if not session:
        return
    interactive_type = str(parsed.get("interactive_type") or "").strip()
    selected_row_id = str(parsed.get("selected_row_id") or parsed.get("interactive_reply_id") or "").strip()
    selected_title = str(parsed.get("selected_title") or parsed.get("interactive_reply_title") or "").strip()
    if interactive_type != "list_reply" or not selected_row_id:
        _log_choice_message_marker("[CHOICE RESUME SKIPPED]", session, selected_row_id=selected_row_id, selected_title=selected_title, reason=f"not_list_reply_or_missing_selected_row_id interactive_type={interactive_type}")
        _log_choice_message_marker("[CHOICE RESUME REASON]", session, selected_row_id=selected_row_id, selected_title=selected_title, reason=f"interactive_type={interactive_type} selected_row_id_present={bool(selected_row_id)}")
        return
    _log_choice_message_marker("[CHOICE MESSAGE RECEIVED]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="persist_interactive_reply_context")
    if session and isinstance(getattr(session, "context", None), dict) and session.context.get("waiting_choice") is True:
        _log_choice_message_marker("[CHOICE WAITING SESSION FOUND]", session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="persist_interactive_reply_context")
    else:
        _log_choice_message_marker("[CHOICE RESUME SKIPPED]", session, selected_row_id=selected_row_id, selected_title=selected_title, reason="active_session_not_waiting_choice")
        _log_choice_message_marker("[CHOICE RESUME REASON]", session, selected_row_id=selected_row_id, selected_title=selected_title, reason=f"waiting_choice={((session.context or {}).get('waiting_choice') if session and isinstance(getattr(session, 'context', None), dict) else None)}")
    set_current_node_write_reason(session, "process_incoming_message_persist_interactive_reply_context_context_only")
    session.context = {
        **(session.context or {}),
        "last_interactive_type": interactive_type,
        "last_interactive_list_reply_id": selected_row_id,
        "last_interactive_list_reply_title": selected_title,
        "selected_row_id": selected_row_id,
        "selected_title": selected_title,
        "correlation_id": correlation_id,
        "last_interactive_message_id": correlation_id,
    }
    db.add(session)
    logger.info(
        "[CHOICE LIST RESPONSE] session_id=%s current_node_id=%s choice_node_id=%s selected_row_id=%s target_node_id=%s worker_id=%s correlation_id=%s source=message_worker selected_title=%s",
        session.id,
        getattr(session, "current_node_id", None),
        (session.context or {}).get("choice_node_id") if isinstance(session.context, dict) else None,
        selected_row_id,
        (session.context or {}).get("selected_choice_target_node_id") if isinstance(session.context, dict) else None,
        _worker_id(),
        correlation_id,
        selected_title,
    )



DEDUP_TTL_SECONDS = 600
FLOW_LOCK_TTL_SECONDS = 15


class ConversationLockContendedError(RuntimeError):
    """Retryable signal used by RQ when another worker owns a conversation."""


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
        # GET followed by DEL can delete a *new* owner's lock after our TTL
        # expires. The comparison and deletion must be one Redis operation.
        released = redis_client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0",
            1,
            lock_key,
            lock_token,
        )
        logger.info("event=incoming_worker_lock_released lock_key=%s released=%s", lock_key, bool(released))
    except Exception:
        logger.warning("event=incoming_worker_lock_release_warning lock_key=%s", lock_key, exc_info=True)

def _pick_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    logger.info("[META WORKER RAW PAYLOAD] payload=%s", _json_log_payload(payload))
    normalized = normalize_meta_message(payload)
    logger.info("[NORMALIZE_META_MESSAGE OUTPUT] count=%s payload_shape=%s normalized=%s", len(normalized), _payload_shape(payload), _json_log_payload(normalized))
    if normalized:
        return normalized[0]

    selected_row_id = str(payload.get("selected_row_id") or payload.get("interactive_reply_id") or "").strip()
    selected_title = str(payload.get("selected_title") or payload.get("interactive_reply_title") or "").strip()
    interactive_type = str(payload.get("interactive_type") or ("list_reply" if selected_row_id else "")).strip()
    text = str(payload.get("text") or selected_row_id or "").strip()
    if payload.get("phone") and text:
        _log_direct_message_marker("[META RAW MESSAGE]", payload)
        _log_direct_message_marker("[MESSAGE TYPE DETECTED]", payload)
        direct_message = {
            "phone": str(payload.get("phone") or "").strip(),
            "text": text,
            "type": str(payload.get("type") or ("interactive" if interactive_type else "text")).strip(),
            "message_id": str(payload.get("message_id") or "").strip(),
            "name": str(payload.get("name") or "Cliente").strip(),
            "phone_number_id": str(payload.get("phone_number_id") or "").strip(),
            "interactive_type": interactive_type or None,
            "interactive_reply_id": selected_row_id or None,
            "interactive_reply_title": selected_title or None,
            "selected_row_id": selected_row_id or None,
            "selected_title": selected_title or None,
        }
        if interactive_type == "list_reply":
            _log_direct_message_marker("[INTERACTIVE LIST DETECTED]", payload)
            _log_direct_message_marker("[INTERACTIVE LIST PARSED]", direct_message)
        _log_direct_message_marker("[MESSAGE NORMALIZED]", direct_message)
        return direct_message

    if payload.get("phone"):
        _log_direct_message_marker("[MESSAGE TYPE DETECTED]", payload)
    logger.warning(
        "[MESSAGE PARSE UNSUPPORTED] reason=no_supported_message payload_shape=%s has_phone=%s has_text=%s has_selected_row_id=%s payload=%s",
        _payload_shape(payload),
        bool(payload.get("phone")),
        bool(str(payload.get("text") or "").strip()),
        bool(selected_row_id),
        _json_log_payload(payload),
    )
    return None


def process_incoming_message(payload: dict[str, Any]) -> None:
    unwrapped = unwrap_job_envelope(payload, expected_job_type="inbound_message")
    if unwrapped is None:
        return
    payload = unwrapped
    raw_correlation = payload.get("correlation_id") or payload.get("message_id")
    correlation_id = str(raw_correlation or "n/a")
    logger.info(
        "event=incoming_worker_start correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_start worker_id=%s commit_sha=%s",
        correlation_id,
        "n/a",
        payload.get("phone") or "n/a",
        payload.get("job_id") or "n/a",
        _worker_id(),
        _runtime_commit_sha(),
    )

    parsed = _pick_message(payload)
    if not parsed:
        logger.warning("event=incoming_worker_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_parse reason=no_supported_message", correlation_id, "n/a", payload.get("phone") or "n/a", payload.get("job_id") or "n/a")
        return

    whatsapp_message_id = _extract_whatsapp_message_id(payload, parsed)
    correlation_id = whatsapp_message_id or str(parsed.get("message_id") or correlation_id)
    logger.info(
        "event=incoming_worker_parsed correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_parse type=%s interactive_type=%s selected_row_id=%s selected_title=%s",
        correlation_id,
        "n/a",
        parsed.get("phone") or "n/a",
        payload.get("job_id") or "n/a",
        parsed.get("type") or "text",
        parsed.get("interactive_type") or "n/a",
        parsed.get("selected_row_id") or parsed.get("interactive_reply_id") or "n/a",
        parsed.get("selected_title") or parsed.get("interactive_reply_title") or "n/a",
    )

    redis_client = get_redis_client()

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

        # Before the database row exists, tenant + normalized phone is the
        # stable identity used by the conversation lookup below. This protects
        # the complete mutable inbound path, including conversation creation.
        lock_key = f"wazza:inbound:conversation:{tenant.id}:{str(parsed.get('phone') or '').strip()}"
        lock_token = str(uuid.uuid4())
        acquired_lock = bool(redis_client.set(lock_key, lock_token, ex=FLOW_LOCK_TTL_SECONDS, nx=True))
        if not acquired_lock:
            logger.info(
                "event=incoming_worker_lock_contended tenant_id=%s conversation_identity=%s correlation_id=%s ttl_seconds=%s",
                tenant.id,
                parsed.get("phone") or "n/a",
                correlation_id,
                FLOW_LOCK_TTL_SECONDS,
            )
            # Do not acknowledge competing work as processed. RQ performs a
            # bounded retry/backoff, preserving order without busy waiting.
            raise ConversationLockContendedError(f"conversation lock contended tenant_id={tenant.id}")

        provider = None
        provider_id = None
        if phone_number_id:
            provider = (
                db.execute(
                    select(TenantWhatsAppProvider)
                    .where(
                        TenantWhatsAppProvider.tenant_id == tenant.id,
                        TenantWhatsAppProvider.phone_number_id == phone_number_id,
                    )
                    .order_by(
                        TenantWhatsAppProvider.is_active.desc(),
                        TenantWhatsAppProvider.updated_at.desc(),
                        TenantWhatsAppProvider.created_at.desc(),
                    )
                )
                .scalars()
                .first()
            )
            provider_id = str(provider.id) if provider else None

        logger.info(
            "event=incoming_worker_tenant_resolved correlation_id=%s tenant_id=%s provider_id=%s phone=%s job_id=%s stage=incoming_worker_tenant",
            correlation_id,
            tenant.id,
            provider_id or "n/a",
            parsed.get("phone") or "n/a",
            payload.get("job_id") or "n/a",
        )
        logger.info(
            "[WEBHOOK TENANT RESOLVED]\ntenant_id=%s\nphone_number_id=%s",
            tenant.id,
            phone_number_id,
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
            selected_flow = resolve_runtime_flow_for_conversation(
                db=db,
                tenant_id=tenant.id,
                conversation=persisted_conversation,
                message_text=text,
                is_interactive_reply=bool(parsed.get("interactive_type")),
            )
            if selected_flow:
                selected_runtime = resolve_flow_runtime(selected_flow)
                logger.info(
                    "[FLOW SELECTED]\nflow_id=%s\nruntime=%s\npublished_version_id=%s",
                    selected_flow.id,
                    selected_runtime,
                    selected_flow.published_version_id,
                )
            if selected_flow and resolve_flow_runtime(selected_flow) == "v2":
                bind_conversation_to_flow(db, conversation=persisted_conversation, flow=selected_flow)
                flow_v2_session_filters = {
                    "tenant_id": str(tenant.id),
                    "flow_version_id": str(selected_flow.published_version_id),
                    "external_user_id": contact.phone if contact else phone,
                    "conversation_id": str(persisted_conversation.id),
                    "contact_id": str(contact.id) if contact else None,
                    "order_by": "active status first, updated_at desc, started_at desc",
                    "limit": 2,
                }
                logger.info(
                    "event=message_worker_before_flow_v2_session_lookup tenant_id=%s conversation_id=%s contact_id=%s phone=%s flow_id=%s provider_id=%s filters=%s",
                    tenant.id,
                    persisted_conversation.id,
                    contact.id if contact else None,
                    contact.phone if contact else phone,
                    selected_flow.id,
                    provider_id,
                    flow_v2_session_filters,
                )
                FlowRuntimeSelector().dispatch(
                    db=db,
                    flow=selected_flow,
                    tenant_id=tenant.id,
                    phone=contact.phone if contact else phone,
                    message_text=text,
                    conversation=persisted_conversation,
                    contact_id=contact.id if contact else None,
                    input_message_id=correlation_id,
                    metadata={
                        "source": "message_worker",
                        "job_id": payload.get("job_id"),
                        "message_type": parsed.get("type") or "text",
                        "phone_number_id": phone_number_id,
                        "provider_id": provider_id,
                        "interactive_type": parsed.get("interactive_type"),
                        "selected_row_id": parsed.get("selected_row_id") or parsed.get("interactive_reply_id"),
                        "interactive_reply_id": parsed.get("interactive_reply_id"),
                        "interactive_reply_title": parsed.get("interactive_reply_title"),
                        "selected_title": parsed.get("selected_title") or parsed.get("interactive_reply_title"),
                        "row_id": parsed.get("selected_row_id") or parsed.get("interactive_reply_id"),
                        "message_text": text,
                    },
                )
                logger.info(
                    "[FLOW RUNTIME SELECTOR] skipped_v1=true runtime=v2 tenant_id=%s flow_id=%s conversation_id=%s correlation_id=%s",
                    tenant.id,
                    selected_flow.id,
                    persisted_conversation.id,
                    correlation_id,
                )
            else:
                active_session = None
                if hasattr(db, "query"):
                    active_session = (
                        db.query(FlowSession)
                        .filter(
                            FlowSession.tenant_id == tenant.id,
                            FlowSession.conversation_id == str(persisted_conversation.id),
                        )
                        .order_by(FlowSession.updated_at.desc(), FlowSession.created_at.desc())
                        .first()
                    )
                selected_row_id = str(parsed.get("selected_row_id") or parsed.get("interactive_reply_id") or "").strip()
                selected_title = str(parsed.get("selected_title") or parsed.get("interactive_reply_title") or "").strip()
                if str(parsed.get("interactive_type") or "").strip() == "list_reply":
                    _log_choice_message_marker("[CHOICE MESSAGE RECEIVED]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="persist_interactive_reply_context")
                if active_session and (active_session.status or "").lower() not in FINAL_SESSION_STATUSES:
                    if isinstance(getattr(active_session, "context", None), dict) and active_session.context.get("waiting_choice") is True:
                        _log_choice_message_marker("[CHOICE WAITING SESSION FOUND]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, correlation_id=correlation_id, reason="persist_interactive_reply_context")
                    _persist_interactive_reply_context(db, active_session, parsed, correlation_id=correlation_id)
                elif str(parsed.get("interactive_type") or "").strip() == "list_reply":
                    _log_choice_message_marker("[CHOICE RESUME SKIPPED]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, reason="no_active_non_final_session")
                    _log_choice_message_marker("[CHOICE RESUME REASON]", active_session, selected_row_id=selected_row_id, selected_title=selected_title, reason=f"active_session={bool(active_session)} status={getattr(active_session, 'status', None)}")
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

        try:
            message_payload = {
                "event": "message",
                "message": MessageOut.model_validate(
                    persisted_message
                ).model_dump(mode="json"),
            }
            ws_channel = (
                f"{tenant.id}:{persisted_conversation.id}"
            )

            sse_channel = (
                f"{tenant.id}:{persisted_conversation.phone_number}"
            )

            logger.warning(
                "[REDIS PUBLISH] ws=%s sse=%s",
                ws_channel,
                sse_channel
            )

            from app.services.realtime_service import sync_publish
            sync_publish(ws_channel, message_payload)
            sync_publish(sse_channel, message_payload)

            dashboard_channel = f"dashboard:{tenant.id}"
            dashboard_payload = {
                "refresh": ["conversations"],
            }
            sync_publish(dashboard_channel, dashboard_payload)

            logger.warning(
                "[REDIS PUBLISH SUCCESS] ws=%s sse=%s dashboard=%s",
                ws_channel,
                sse_channel,
                dashboard_channel,
            )

        except Exception:
            logger.exception(
                "[WS BROADCAST ERROR]"
            )

    except Exception:
        if db.in_transaction():
            db.rollback()
        raise
    finally:
        if lock_key and lock_token:
            _release_session_lock(redis_client, lock_key, lock_token)
        db.close()


    logger.info("event=incoming_worker_done correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_worker_done", correlation_id, payload.get("tenant_id") or "n/a", parsed.get("phone") if parsed else payload.get("phone") or "n/a", payload.get("job_id") or "n/a")
