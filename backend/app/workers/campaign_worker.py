from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime

from redis import Redis
from rq import Retry
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.whatsapp_campaign import WhatsAppCampaign, WhatsAppCampaignRecipient
from app.models.contact import Contact
from app.services.queue import get_queue
from app.services.whatsapp_message_service import send_template_message
from app.services.contact_event_service import register_contact_event

logger = logging.getLogger(__name__)

CHUNK_SIZE = int(os.getenv("CAMPAIGN_CHUNK_SIZE", "200"))
MIN_DELAY_SECONDS = float(os.getenv("CAMPAIGN_MIN_DELAY_SECONDS", "2"))
MAX_DELAY_SECONDS = float(os.getenv("CAMPAIGN_MAX_DELAY_SECONDS", "4"))


def _refresh_campaign_metrics(db, campaign: WhatsAppCampaign) -> None:
    campaign.total_recipients = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id)).scalar() or 0
    campaign.total_sent = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status.in_(["sent", "delivered", "read"]))).scalar() or 0
    campaign.total_failed = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status.in_(["failed", "failed_missing_variable"]))).scalar() or 0
    if campaign.total_recipients > 0 and campaign.total_sent + campaign.total_failed >= campaign.total_recipients:
        campaign.status = "completed"
        campaign.completed_at = datetime.utcnow()
    logger.info("[CAMPAIGN METRICS UPDATE] campaign_id=%s total=%s sent=%s failed=%s", campaign.id, campaign.total_recipients, campaign.total_sent, campaign.total_failed)


def process_campaign(campaign_id: str, tenant_id: str) -> None:
    redis_conn = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    lock_key = f"campaign:lock:{campaign_id}"
    if not redis_conn.set(lock_key, "1", ex=900, nx=True):
        logger.warning("campaign already running campaign_id=%s", campaign_id)
        return

    try:
        with SessionLocal() as db:
            logger.info("[CAMPAIGN START] campaign_id=%s tenant_id=%s", campaign_id, tenant_id)
            campaign = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant_id)).scalars().first()
            if not campaign:
                return
            if campaign.status == "cancelled":
                return
            campaign.status = "running"
            campaign.started_at = campaign.started_at or datetime.utcnow()
            pending = db.execute(
                select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status == "pending").limit(CHUNK_SIZE)
            ).scalars().all()
            queue = get_queue("normal")
            for rec in pending:
                rec.status = "queued"
                logger.info("[CAMPAIGN ENQUEUE] campaign_id=%s recipient_id=%s phone=%s", campaign.id, rec.id, rec.phone)
                queue.enqueue("app.workers.campaign_worker.process_campaign_recipient", str(rec.id), retry=Retry(max=3, interval=[5, 20, 60]), job_timeout=120)
            _refresh_campaign_metrics(db, campaign)
            db.commit()
    finally:
        redis_conn.delete(lock_key)


def process_campaign_recipient(recipient_id: str) -> None:
    with SessionLocal() as db:
        recipient = db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.id == recipient_id)).scalars().first()
        if not recipient:
            return
        campaign = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == recipient.campaign_id)).scalars().first()
        if not campaign or campaign.status in {"paused", "cancelled"}:
            return
        try:
            contact = db.execute(
                select(Contact).where(
                    Contact.tenant_id == campaign.tenant_id,
                    Contact.phone == recipient.phone,
                )
            ).scalars().first()
            recipient_variables = recipient.variables_json if isinstance(recipient.variables_json, dict) else {}
            contact_custom_fields = contact.custom_fields_json if contact and isinstance(contact.custom_fields_json, dict) else {}
            contact_name = str(contact.name or "").strip() if contact else ""
            first_name_from_name = (contact_name.split(" ", 1)[0] if contact_name else "").strip()

            first_name_value = (
                str(recipient_variables.get("first_name") or "").strip()
                or (str(contact.first_name or "").strip() if contact else "")
                or first_name_from_name
                or "cliente"
            )
            name_value = (
                str(recipient_variables.get("name") or "").strip()
                or contact_name
                or "cliente"
            )
            phone_value = (
                (str(contact.phone or "").strip() if contact else "")
                or str(recipient.phone or "").strip()
            )
            order_number_value = (
                str(recipient_variables.get("order_number") or "").strip()
                or str(contact_custom_fields.get("order_number") or "").strip()
                or str(contact_custom_fields.get("pedido") or "").strip()
                or ""
            )

            variable_mapping = recipient_variables.get("_variable_mapping") if isinstance(recipient_variables.get("_variable_mapping"), dict) else {}
            mapping_errors = recipient_variables.get("_variable_mapping_errors") if isinstance(recipient_variables.get("_variable_mapping_errors"), dict) else {}
            variables_resolved = {
                **recipient_variables,
                "first_name": first_name_value,
                "name": name_value,
                "phone": phone_value,
                "order_number": order_number_value,
            }
            missing_variables: list[str] = []
            for template_var, mapping in variable_mapping.items():
                if not isinstance(mapping, dict):
                    continue
                mapping_type = str(mapping.get("type") or "").strip()
                field = str(mapping.get("field") or "").strip()
                if mapping_type == "fixed":
                    variables_resolved[str(template_var)] = str(mapping.get("value") or "").strip()
                elif mapping_type == "contact_field":
                    if field == "first_name":
                        variables_resolved[str(template_var)] = first_name_value
                    elif field in {"full_name", "name"}:
                        variables_resolved[str(template_var)] = name_value
                    elif field == "phone":
                        variables_resolved[str(template_var)] = phone_value
                    elif field == "email":
                        variables_resolved[str(template_var)] = str(contact.email or "").strip() if contact else ""
                elif mapping_type == "custom_field":
                    custom_value = str(contact_custom_fields.get(field) or "").strip()
                    variables_resolved[str(template_var)] = custom_value
                    if not custom_value:
                        mapping_errors[str(template_var)] = f"Campo personalizado {field} não existe para este contato. Use valor fixo ou importe esse campo no contato."

            for required in [k for k in variables_resolved.keys() if str(k).isdigit()]:
                if not str(variables_resolved.get(required) or "").strip():
                    missing_variables.append(str(required))

            logger.info(
                "[CAMPAIGN VARIABLES RESOLVE START] campaign_id=%s recipient_id=%s phone=%s",
                campaign.id,
                recipient.id,
                recipient.phone,
            )
            logger.info(
                "[CAMPAIGN VARIABLES RESOLVED] campaign_id=%s recipient_id=%s variables=%s",
                campaign.id,
                recipient.id,
                variables_resolved,
            )
            if mapping_errors or missing_variables:
                missing_label = missing_variables[0] if missing_variables else None
                recipient.status = "failed_missing_variable"
                recipient.failed_at = datetime.utcnow()
                if mapping_errors:
                    first_var = sorted(mapping_errors.keys(), key=lambda x: int(x) if str(x).isdigit() else 9999)[0]
                    recipient.error_message = f"Variável {first_var} está vazia porque {str(variable_mapping.get(first_var, {}).get('field') or 'campo personalizado')} não existe no contato."
                else:
                    recipient.error_message = f"Variável obrigatória {missing_label} não preenchida."
                logger.warning(
                    "[CAMPAIGN VARIABLES MISSING] campaign_id=%s recipient_id=%s missing=%s",
                    campaign.id,
                    recipient.id,
                    missing_variables,
                )
                _refresh_campaign_metrics(db, campaign)
                db.commit()
                return

            logger.info("[CAMPAIGN RECIPIENT SEND] campaign_id=%s recipient_id=%s phone=%s", campaign.id, recipient.id, recipient.phone)
            result = send_template_message(
                db,
                tenant_id=str(campaign.tenant_id),
                provider_id=str(campaign.provider_id),
                template_id=str(campaign.template_id),
                to=recipient.phone,
                variables=variables_resolved,
            )
            recipient.status = "sent"
            recipient.sent_at = result.get("sent_at")
            recipient.provider_message_id = result.get("provider_message_id")
            if contact:
                register_contact_event(
                    db,
                    tenant_id=campaign.tenant_id,
                    contact_id=contact.id,
                    event_type="campaign_sent",
                    title="Campanha enviada",
                    description=f"Recebeu campanha {campaign.name}",
                    metadata={"campaign_id": str(campaign.id), "campaign_name": campaign.name},
                    contact=contact,
                )
            logger.info("[CAMPAIGN RECIPIENT SENT] campaign_id=%s recipient_id=%s provider_message_id=%s", campaign.id, recipient.id, recipient.provider_message_id)
        except Exception as exc:
            recipient.status = "failed"
            recipient.failed_at = datetime.utcnow()
            recipient.error_message = str(exc)[:1000]
            logger.error("[CAMPAIGN RECIPIENT FAILED] campaign_id=%s recipient_id=%s error=%s", campaign.id, recipient.id, recipient.error_message)
        _refresh_campaign_metrics(db, campaign)
        time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        db.commit()
