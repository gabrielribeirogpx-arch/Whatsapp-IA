from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.db.session import SessionLocal
from app.core.redis_client import get_redis_client
from app.models import Tenant
from app.services.whatsapp_service import (
    send_whatsapp_interactive_buttons,
    send_whatsapp_message as send_whatsapp_text_message,
)

logger = logging.getLogger(__name__)


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
            tenant = db.query(Tenant).filter(Tenant.id == tenant_uuid).first()
            if not tenant:
                logger.warning(
                    "event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=tenant_not_found",
                    correlation_id,
                    tenant_id,
                    phone,
                    job_id,
                )
                return

        tenant_phone_number_id = str(getattr(tenant, "phone_number_id", "") or "").strip()
        tenant_token = str(getattr(tenant, "whatsapp_token", "") or "").strip()

        resolved_phone_number_id = (
            tenant_phone_number_id
            or str(os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
            or str(os.getenv("PHONE_NUMBER_ID") or "").strip()
        )
        resolved_token = tenant_token or str(os.getenv("WHATSAPP_TOKEN") or "").strip()

        if not resolved_phone_number_id or not resolved_token:
            logger.error(
                "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=missing_whatsapp_credentials has_phone_number_id=%s has_token=%s",
                correlation_id,
                tenant_id,
                phone,
                job_id,
                bool(resolved_phone_number_id),
                bool(resolved_token),
            )
            return

        tenant.phone_number_id = resolved_phone_number_id
        tenant.whatsapp_token = resolved_token

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
    finally:
        _release_send_lock(redis_client, lock_key, lock_token)
        logger.info("[OUTBOUND SEND LOCK RELEASED] tenant_id=%s phone=%s", tenant_id, phone)
