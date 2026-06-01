from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from rq import get_current_job

from app.db.session import SessionLocal
from app.core.redis_client import get_redis_client
from sqlalchemy import select

from app.models import Tenant
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.idempotency_service import register_processed_message
from app.services.whatsapp_message_service import (
    mark_provider_auth_error,
    resolve_active_meta_provider_credentials,
    send_buttons_message_via_meta,
    send_text_message_via_meta,
)
from app.services.whatsapp_credentials_service import WhatsAppCredentialsNotConfiguredError, get_tenant_whatsapp_credentials
from app.integrations.meta.meta_cloud_client import MetaApiError

logger = logging.getLogger(__name__)


def _token_hash(token: str | None) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _record_outbound_message(*, db, tenant_id: uuid.UUID, phone: str, text: str, message_id: str, flow_id: Any = None, flow_version_id: Any = None, flow_session_id: Any = None, node_id: Any = None) -> None:
    if not register_processed_message(db=db, tenant_id=tenant_id, message_id=message_id):
        logger.info("[OUTBOUND MESSAGE RECORD SKIPPED_DUPLICATE] tenant_id=%s conversation_id=%s flow_id=%s node_id=%s", tenant_id, "n/a", flow_id, node_id)
        return

    conversation = (
        db.execute(
            select(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not conversation:
        return

    outbound = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        text=text,
        from_me=True,
    )
    conversation.updated_at = outbound.created_at
    db.add(outbound)
    db.commit()
    logger.info(
        "[OUTBOUND MESSAGE RECORDED] tenant_id=%s conversation_id=%s flow_id=%s node_id=%s status=sent direction=outbound flow_version_id=%s flow_session_id=%s",
        tenant_id,
        conversation.id,
        flow_id,
        node_id,
        flow_version_id,
        flow_session_id,
    )


def _release_send_lock(redis_client: Any, lock_key: str, lock_token: str) -> None:
    try:
        current = redis_client.get(lock_key)
        if current == lock_token:
            redis_client.delete(lock_key)
    except Exception:
        logger.warning("[OUTBOUND SEND LOCK RELEASED] lock_key=%s release_error=true", lock_key, exc_info=True)


def send_whatsapp_message(*, message_data: dict[str, Any]) -> None:
    tenant_id = str(message_data.get("tenant_id") or "")
    phone = str(message_data.get("phone") or "")
    text = str(message_data.get("text") or "").strip()
    buttons = message_data.get("buttons")
    correlation_id = str(message_data.get("correlation_id") or message_data.get("message_id") or "n/a")
    job_id = str(message_data.get("job_id") or "n/a")
    sequence_number_raw = message_data.get("sequence_number")
    flow_id = message_data.get("flow_id")
    flow_version_id = message_data.get("flow_version_id")
    session_id = message_data.get("session_id")
    node_id = message_data.get("node_id")
    flow_session_id = message_data.get("session_id")
    conversation_id = str(message_data.get("conversation_id") or "") or None
    is_flow_message = bool(flow_id or flow_version_id or session_id or node_id or sequence_number_raw is not None)

    logger.info("event=send_worker_start correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_start", correlation_id, tenant_id or "n/a", phone or "n/a", job_id)

    lock_key = f"wa:send-lock:{tenant_id}:{phone}"
    last_sent_key = f"wa:last-sent-seq:{tenant_id}:{phone}"
    lock_token = str(uuid.uuid4())
    redis_client = get_redis_client()
    lock_acquired = bool(redis_client.set(lock_key, lock_token, ex=30, nx=True))
    if not lock_acquired:
        logger.info("[OUTBOUND SEND LOCK ACQUIRED] tenant_id=%s phone=%s acquired=false", tenant_id, phone)
        return
    logger.info("[OUTBOUND SEND LOCK ACQUIRED] tenant_id=%s phone=%s acquired=true", tenant_id, phone)

    try:
        sequence_number: int | None = None
        if sequence_number_raw is not None:
            try:
                sequence_number = int(sequence_number_raw)
            except (TypeError, ValueError):
                sequence_number = None
        last_sent_raw = redis_client.get(last_sent_key)
        last_sent_seq = int(last_sent_raw) if str(last_sent_raw or "").isdigit() else None
        logger.info("[OUTBOUND SEND SEQUENCE] tenant_id=%s phone=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s current_sequence=%s last_sent_sequence=%s", tenant_id, phone, flow_id, flow_version_id, session_id, node_id, sequence_number, last_sent_seq)
        if sequence_number is not None and last_sent_seq is not None and sequence_number < last_sent_seq:
            logger.warning("[OUTBOUND STALE MESSAGE DROPPED] tenant_id=%s phone=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s last_sent_sequence=%s", tenant_id, phone, flow_id, session_id, node_id, sequence_number, last_sent_seq)
            return

        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except (ValueError, TypeError):
            logger.error(
                "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=invalid_tenant_id",
                correlation_id,
                tenant_id or "n/a",
                phone or "n/a",
                job_id,
            )
            return

        with SessionLocal() as db:
            tenant = db.execute(select(Tenant).where(Tenant.id == tenant_uuid)).scalars().first()
            if not tenant:
                logger.warning(
                    "event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=tenant_not_found",
                    correlation_id,
                    tenant_id,
                    phone,
                    job_id,
                )
                return
            if not conversation_id:
                conversation = (
                    db.execute(
                        select(Conversation.id)
                        .where(Conversation.tenant_id == tenant_uuid, Conversation.phone_number == phone)
                        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                conversation_id = str(conversation) if conversation else None

        provider_id: str | None = None
        with SessionLocal() as db:
            active_provider = resolve_active_meta_provider_credentials(db, tenant_id=tenant_id, conversation_id=conversation_id)

        if active_provider:
            resolved_phone_number_id = active_provider["phone_number_id"]
            resolved_token = active_provider["token"]
            provider_id = active_provider["provider_id"]
            logger.info(
                "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s updated_at=%s send_endpoint=/%s/messages",
                provider_id,
                tenant_id,
                active_provider.get("provider_name"),
                resolved_phone_number_id,
                active_provider.get("waba_id"),
                active_provider.get("business_id"),
                active_provider.get("status"),
                active_provider.get("is_active"),
                bool(resolved_token),
                len(resolved_token or ""),
                active_provider.get("updated_at"),
                resolved_phone_number_id,
            )
        else:
            try:
                credentials = get_tenant_whatsapp_credentials(tenant_id)
                resolved_phone_number_id = credentials["phone_number_id"]
                resolved_token = credentials["token"]
                logger.warning(
                    "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s source=legacy_credentials",
                    None,
                    tenant_id,
                    "legacy_credentials",
                    resolved_phone_number_id,
                    None,
                    None,
                    "legacy",
                    False,
                    bool(resolved_token),
                    len(resolved_token or ""),
                )
            except WhatsAppCredentialsNotConfiguredError:
                logger.error(
                    "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=missing_whatsapp_credentials error=[WHATSAPP NOT CONFIGURED] tenant_id=%s",
                    correlation_id,
                    tenant_id,
                    phone,
                    job_id,
                    tenant_id,
                )
                return

        token_hash = _token_hash(resolved_token)
        waba_id = active_provider.get("waba_id") if active_provider else None
        business_id = active_provider.get("business_id") if active_provider else None
        business_account_id = waba_id or business_id
        provider_source = "active_provider" if active_provider else "legacy_credentials"
        meta_endpoint = f"/{resolved_phone_number_id}/messages"
        context = {
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "token_length": len(resolved_token or ""),
            "token_hash": token_hash,
            "phone_number_id": resolved_phone_number_id,
            "business_account_id": business_account_id,
            "waba_id": waba_id,
            "business_id": business_id,
            "source": provider_source,
            "flow_id": flow_id,
            "flow_version_id": flow_version_id,
            "session_id": session_id,
            "node_id": node_id,
            "sequence_number": sequence_number,
        }
        if is_flow_message:
            logger.info(
                "[FLOW MESSAGE PROVIDER] tenant_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s provider_id=%s phone_number_id=%s business_account_id=%s waba_id=%s business_id=%s token_hash=%s provider_source=%s provider_updated_at=%s message_text=%s",
                tenant_id,
                flow_id,
                flow_version_id,
                session_id,
                node_id,
                sequence_number,
                provider_id,
                resolved_phone_number_id,
                business_account_id,
                waba_id,
                business_id,
                token_hash,
                provider_source,
                active_provider.get("updated_at") if active_provider else None,
                text,
            )
            logger.info(
                "[FLOW MESSAGE META REQUEST] endpoint=%s phone_number_id=%s provider_id=%s tenant_id=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s",
                meta_endpoint,
                resolved_phone_number_id,
                provider_id,
                tenant_id,
                flow_id,
                session_id,
                node_id,
                sequence_number,
            )
        try:
            if buttons:
                send_buttons_message_via_meta(
                    to=phone,
                    body_text=text,
                    buttons=buttons,
                    token=resolved_token,
                    phone_number_id=resolved_phone_number_id,
                    context=context,
                )
            else:
                send_text_message_via_meta(
                    to=phone,
                    text=text,
                    token=resolved_token,
                    phone_number_id=resolved_phone_number_id,
                    context=context,
                )
        except MetaApiError as exc:
            if exc.status_code == 401 and provider_id:
                logger.error("[WHATSAPP SEND AUTH ERROR] tenant_id=%s provider_id=%s phone=%s", tenant_id, provider_id, phone)
                with SessionLocal() as db:
                    mark_provider_auth_error(db, provider_id=provider_id, error_message=str(exc))
            raise

        logger.info(
            "event=queue_send_success correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_final text_len=%s has_buttons=%s",
            correlation_id,
            tenant_id,
            phone,
            job_id,
            len(text),
            bool(buttons),
        )
        if sequence_number is not None:
            redis_client.set(last_sent_key, sequence_number)

        current_job = get_current_job()
        dedupe_message_id = str(message_data.get("message_id") or message_data.get("job_id") or getattr(current_job, "id", None) or correlation_id)
        with SessionLocal() as db:
            _record_outbound_message(
                db=db,
                tenant_id=tenant_uuid,
                phone=phone,
                text=text,
                message_id=f"outbound:{dedupe_message_id}",
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                flow_session_id=flow_session_id,
                node_id=node_id,
            )
    finally:
        _release_send_lock(redis_client, lock_key, lock_token)
        logger.info("[OUTBOUND SEND LOCK RELEASED] tenant_id=%s phone=%s", tenant_id, phone)
