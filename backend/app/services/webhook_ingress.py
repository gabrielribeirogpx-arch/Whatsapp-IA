import logging
from fastapi import Request

from app.services.queue import enqueue_incoming_message

logger = logging.getLogger(__name__)


async def enqueue_webhook_payload(request: Request) -> tuple[bool, str | None]:
    """
    Entrada assíncrona padrão para webhooks: parse JSON, tenta enfileirar e
    sempre retorna ACK imediato para o integrador (sem bloquear em processamento).
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("event=webhook_invalid_json")
        return False, None

    if not isinstance(payload, dict):
        logger.warning("event=webhook_invalid_payload_type type=%s", type(payload).__name__)
        return False, None

    correlation_id: str | None = None
    try:
        entry = (payload.get("entry") or [None])[0] or {}
        changes = (entry.get("changes") or [None])[0] or {}
        value = changes.get("value") or {}
        message = (value.get("messages") or [None])[0] or {}
        correlation_id = (message.get("id") or payload.get("message_id") or "").strip() or None
        if correlation_id:
            payload["correlation_id"] = correlation_id
            payload.setdefault("message_id", correlation_id)
    except Exception:
        logger.exception("event=webhook_correlation_parse_error")

    try:
        enqueue_incoming_message(payload)
        return True, correlation_id
    except Exception:
        logger.exception("event=webhook_enqueue_error correlation_id=%s", correlation_id)
        return False, correlation_id
