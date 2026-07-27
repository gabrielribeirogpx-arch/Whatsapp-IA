import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.services.queue import enqueue_incoming_message
from app.db.session import SessionLocal
from app.models import Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_campaign import WhatsAppCampaign, WhatsAppCampaignRecipient
from sqlalchemy import select

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundTenantResolution:
    tenant_id: str | None
    provider_id: str | None
    phone_number_id: str | None
    reason: str | None = None
    connection_type: str | None = None
    coexistence_enabled: bool = False


def _extract_first_meta_value(payload: dict[str, Any]) -> dict[str, Any]:
    entry = (payload.get("entry") or [None])[0] or {}
    change = (entry.get("changes") or [None])[0] or {}
    value = change.get("value") or {}
    return value if isinstance(value, dict) else {}


def _extract_inbound_phone_number_id(payload: dict[str, Any]) -> str | None:
    value = _extract_first_meta_value(payload)
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    candidates = (
        metadata.get("phone_number_id"),
        value.get("phone_number_id"),
        payload.get("phone_number_id"),
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return None


def _resolve_inbound_tenant(db, payload: dict[str, Any]) -> InboundTenantResolution:
    phone_number_id = _extract_inbound_phone_number_id(payload)
    if not phone_number_id:
        return InboundTenantResolution(None, None, None, "missing_phone_number_id")

    provider = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(TenantWhatsAppProvider.phone_number_id == phone_number_id)
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
                TenantWhatsAppProvider.created_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    if provider:
        return InboundTenantResolution(str(provider.tenant_id), str(provider.id), phone_number_id, connection_type=getattr(provider, "connection_type", None) or "cloud_api", coexistence_enabled=bool(getattr(provider, "coexistence_enabled", False)))

    tenant = db.execute(select(Tenant).where(Tenant.phone_number_id == phone_number_id)).scalars().first()
    if tenant:
        return InboundTenantResolution(str(tenant.id), None, phone_number_id)

    return InboundTenantResolution(None, None, phone_number_id, "provider_not_found")


def _redact_message_content(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if key in {"text", "body", "caption"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_message_content(item)
        return redacted
    if isinstance(value, list):
        return [_redact_message_content(item) for item in value]
    return value


def _json_log_payload(payload: object) -> str:
    try:
        return json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(payload)


def _safe_webhook_log_payload(payload: dict[str, Any]) -> str:
    return _json_log_payload(_redact_message_content(payload))


def _log_interactive_ingress(payload: dict[str, Any], *, correlation_id: str) -> None:
    """Log the Meta envelope before it crosses the API/worker boundary."""
    value = _extract_first_meta_value(payload)
    for message in value.get("messages", []) if isinstance(value.get("messages"), list) else []:
        if not isinstance(message, dict):
            continue
        interactive = message.get("interactive") if isinstance(message.get("interactive"), dict) else {}
        button_reply = interactive.get("button_reply") if isinstance(interactive.get("button_reply"), dict) else {}
        logger.info(
            "event=meta_webhook_interactive_pipeline stage=webhook_received correlation_id=%s "
            "message.type=%s interactive.type=%s button_reply.id=%s interactive_reply_id=%s "
            "selected_row_id=%s row_id=%s runtime_choice_key=%s current_node_id=%s next_node_id=%s raw_payload=%s",
            correlation_id,
            message.get("type") or "n/a",
            interactive.get("type") or "n/a",
            button_reply.get("id") or "n/a",
            "n/a", "n/a", "n/a", "n/a", "n/a", "n/a",
            _json_log_payload(payload),
        )


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
    rows = db.execute(
        select(WhatsAppCampaignRecipient)
        .join(WhatsAppCampaign, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
        .where(
            WhatsAppCampaign.tenant_id == campaign.tenant_id,
            WhatsAppCampaignRecipient.campaign_id == campaign.id,
        )
    ).scalars().all()
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
                campaign = db.execute(
                    select(WhatsAppCampaign)
                    .join(WhatsAppCampaignRecipient, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
                    .where(WhatsAppCampaignRecipient.provider_message_id == provider_message_id)
                ).scalars().first()
                if not campaign:
                    continue
                rec = db.execute(
                    select(WhatsAppCampaignRecipient)
                    .join(WhatsAppCampaign, WhatsAppCampaignRecipient.campaign_id == WhatsAppCampaign.id)
                    .where(
                        WhatsAppCampaign.tenant_id == campaign.tenant_id,
                        WhatsAppCampaignRecipient.provider_message_id == provider_message_id,
                    )
                ).scalars().first()
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

    logger.info("[META WEBHOOK PAYLOAD] payload=%s", _safe_webhook_log_payload(payload))

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

    _log_interactive_ingress(payload, correlation_id=correlation_id)

    _log_media_delivery_statuses(payload)
    _update_campaign_status_from_meta(payload)

    try:
        with SessionLocal() as db:
            resolution = _resolve_inbound_tenant(db, payload)
        if not resolution.tenant_id:
            logger.warning(
                "event=inbound_tenant_resolution_failed correlation_id=%s phone_number_id=%s provider_id=%s reason=%s",
                correlation_id,
                resolution.phone_number_id or "n/a",
                resolution.provider_id or "n/a",
                resolution.reason or "unknown",
            )
            return False, correlation_id

        payload["tenant_id"] = resolution.tenant_id
        if resolution.provider_id:
            payload["provider_id"] = resolution.provider_id
        if resolution.phone_number_id:
            payload["phone_number_id"] = resolution.phone_number_id
        value = _extract_first_meta_value(payload)
        message = (value.get("messages") or [None])[0] or {}
        if resolution.connection_type == "cloud_api_coexistence" or resolution.coexistence_enabled:
            logger.info("META_WEBHOOK_COEX_CONTEXT tenant_id=%s phone_number_id=%s provider_id=%s connection_type=%s coexistence_enabled=%s message_type=%s source=%s", resolution.tenant_id, resolution.phone_number_id, resolution.provider_id, resolution.connection_type or "cloud_api", resolution.coexistence_enabled, message.get("type") or "unknown", "meta_webhook")

        job_id = enqueue_incoming_message(payload)
        logger.info(
            "event=inbound_enqueued correlation_id=%s tenant_id=%s provider_id=%s phone_number_id=%s job_id=%s stage=webhook_enqueue",
            correlation_id,
            resolution.tenant_id,
            resolution.provider_id or "n/a",
            resolution.phone_number_id or "n/a",
            job_id,
        )
        return True, correlation_id
    except Exception:
        logger.exception("event=webhook_enqueue_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=webhook_enqueue", correlation_id, payload.get("tenant_id") or "n/a", payload.get("phone") or "n/a", "n/a")
        return False, correlation_id
