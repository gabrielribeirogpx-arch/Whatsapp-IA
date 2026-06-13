import json
import logging
import uuid

from fastapi import Request

from app.services.queue import enqueue_incoming_message
from app.db.session import SessionLocal
from app.models.whatsapp_campaign import WhatsAppCampaign, WhatsAppCampaignRecipient
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _json_log_payload(payload: object) -> str:
    try:
        return json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(payload)


def _log_media_delivery_statuses(payload: dict) -> None:
    try:
        entry = (payload.get("entry") or [None])[0] or {}
        change = (entry.get("changes") or [None])[0] or {}
        value = change.get("value") or {}
        statuses = value.get("statuses") or []
        for status_payload in statuses:
            status = str(status_payload.get("status") or "").lower()
            if status not in {"failed", "sent", "delivered"}:
                continue
            conversation = status_payload.get("conversation") or {}
            pricing = status_payload.get("pricing") or {}
            errors = status_payload.get("errors") or []
            logger.info(
                "[MEDIA WEBHOOK STATUS] message_id=%s status=%s recipient_id=%s conversation_id=%s pricing_category=%s errors=%s raw_status=%s",
                status_payload.get("id"),
                status,
                status_payload.get("recipient_id"),
                conversation.get("id"),
                pricing.get("category"),
                _json_log_payload(errors),
                _json_log_payload(status_payload),
            )
    except Exception:
        logger.exception("event=media_webhook_status_log_error")


def _recalculate_campaign_metrics(db, campaign: WhatsAppCampaign) -> None:
    rows = db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == campaign.id)).scalars().all()
    campaign.total_recipients = len(rows)
    campaign.total_sent = sum(1 for r in rows if r.status in {"sent", "delivered", "read"})
    campaign.total_delivered = sum(1 for r in rows if r.status in {"delivered", "read"})
    campaign.total_read = sum(1 for r in rows if r.status == "read")
    campaign.total_failed = sum(1 for r in rows if r.status == "failed")




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
                    if status=="delivered": rec.delivered_at=ts
                    if status=="read": rec.read_at=ts
                    if status=="failed": rec.failed_at=ts
                    _recalculate_campaign_metrics(db, campaign)
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

    logger.info("[META WEBHOOK RAW PAYLOAD] payload=%s", _json_log_payload(payload))

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

    _log_media_delivery_statuses(payload)
    _update_campaign_status_from_meta(payload)

    try:
        job_id = enqueue_incoming_message(payload)
        logger.info("event=webhook_enqueue_success correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=webhook_enqueue", correlation_id, payload.get("tenant_id") or "n/a", payload.get("phone") or "n/a", job_id)
        return True, correlation_id
    except Exception:
        logger.exception("event=webhook_enqueue_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=webhook_enqueue", correlation_id, payload.get("tenant_id") or "n/a", payload.get("phone") or "n/a", "n/a")
        return False, correlation_id
