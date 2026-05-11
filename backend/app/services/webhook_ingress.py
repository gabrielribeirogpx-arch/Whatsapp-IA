import logging
import uuid

from fastapi import Request

from app.services.queue import enqueue_incoming_message
from app.db.session import SessionLocal
from app.models.whatsapp_campaign import WhatsAppCampaign, WhatsAppCampaignRecipient
from sqlalchemy import select

logger = logging.getLogger(__name__)




def _update_campaign_status_from_meta(payload: dict) -> None:
    try:
        entry=(payload.get("entry") or [None])[0] or {}
        change=(entry.get("changes") or [None])[0] or {}
        value=change.get("value") or {}
        statuses=value.get("statuses") or []
        if not statuses:
            return
        with SessionLocal() as db:
            for st in statuses:
                provider_message_id=str(st.get("id") or "").strip()
                if not provider_message_id:
                    continue
                rec=db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.provider_message_id==provider_message_id)).scalars().first()
                if not rec:
                    continue
                campaign=db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id==rec.campaign_id)).scalars().first()
                status=str(st.get("status") or "").lower()
                ts_raw=st.get("timestamp")
                ts=None
                if ts_raw:
                    from datetime import datetime
                    ts=datetime.utcfromtimestamp(int(ts_raw))
                if status in {"sent","delivered","read","failed"}:
                    rec.status=status
                    if status=="delivered": rec.delivered_at=ts; campaign.total_delivered=int(campaign.total_delivered or 0)+1
                    if status=="read": rec.read_at=ts; campaign.total_read=int(campaign.total_read or 0)+1
                    if status=="failed": rec.failed_at=ts; campaign.total_failed=int(campaign.total_failed or 0)+1
            db.commit()
    except Exception:
        logger.exception("event=campaign_status_update_error")


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

    correlation_id = str(payload.get("message_id") or "").strip() or str(uuid.uuid4())
    payload["correlation_id"] = correlation_id
    payload.setdefault("message_id", correlation_id)

    try:
        entry = (payload.get("entry") or [None])[0] or {}
        changes = (entry.get("changes") or [None])[0] or {}
        value = changes.get("value") or {}
        message = (value.get("messages") or [None])[0] or {}
        message_id = str(message.get("id") or "").strip()
        if message_id:
            correlation_id = message_id
            payload["correlation_id"] = correlation_id
            payload["message_id"] = message_id
    except Exception:
        logger.exception("event=webhook_correlation_parse_error correlation_id=%s stage=webhook_parse", correlation_id)

    _update_campaign_status_from_meta(payload)

    try:
        job_id = enqueue_incoming_message(payload)
        logger.info("event=webhook_enqueue_success correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=webhook_enqueue", correlation_id, payload.get("tenant_id") or "n/a", payload.get("phone") or "n/a", job_id)
        return True, correlation_id
    except Exception:
        logger.exception("event=webhook_enqueue_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=webhook_enqueue", correlation_id, payload.get("tenant_id") or "n/a", payload.get("phone") or "n/a", "n/a")
        return False, correlation_id
