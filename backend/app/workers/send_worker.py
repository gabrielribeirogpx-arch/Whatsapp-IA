from __future__ import annotations

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
from app.services.whatsapp_credentials_service import WhatsAppCredentialsNotConfiguredError, get_tenant_whatsapp_credentials
from app.services.whatsapp_service import (
    send_whatsapp_interactive_buttons,
    send_whatsapp_message as send_whatsapp_text_message,
)

logger = logging.getLogger(__name__)


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

        try:
            credentials = get_tenant_whatsapp_credentials(tenant_id)
            resolved_phone_number_id = credentials["phone_number_id"]
            resolved_token = credentials["token"]
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

        if buttons:
            send_whatsapp_interactive_buttons(
                phone=phone,
                body_text=text,
                buttons=buttons,
                token=resolved_token,
                phone_number_id=resolved_phone_number_id,
            )
        else:
            send_whatsapp_text_message(
                phone=phone,
                text=text,
                token=resolved_token,
                phone_number_id=resolved_phone_number_id,
            )

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
