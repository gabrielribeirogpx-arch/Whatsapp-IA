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
from app.services.queue import get_queue
from app.services.whatsapp_message_service import send_template_message

logger = logging.getLogger(__name__)

CHUNK_SIZE = int(os.getenv("CAMPAIGN_CHUNK_SIZE", "200"))
MIN_DELAY_SECONDS = float(os.getenv("CAMPAIGN_MIN_DELAY_SECONDS", "2"))
MAX_DELAY_SECONDS = float(os.getenv("CAMPAIGN_MAX_DELAY_SECONDS", "4"))


def _refresh_campaign_metrics(db, campaign: WhatsAppCampaign) -> None:
    campaign.total_recipients = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id)).scalar() or 0
    campaign.total_sent = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status.in_(["sent", "delivered", "read"]))).scalar() or 0
    campaign.total_failed = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status == "failed")).scalar() or 0
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
            campaign.status = "running"
            campaign.started_at = campaign.started_at or datetime.utcnow()
            pending = db.execute(
                select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == campaign.id, WhatsAppCampaignRecipient.status.in_(["pending", "failed"])).limit(CHUNK_SIZE)
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
        if not campaign or campaign.status == "paused":
            return
        try:
            logger.info("[CAMPAIGN RECIPIENT SEND] campaign_id=%s recipient_id=%s phone=%s", campaign.id, recipient.id, recipient.phone)
            result = send_template_message(
                db,
                tenant_id=str(campaign.tenant_id),
                provider_id=str(campaign.provider_id),
                template_id=str(campaign.template_id),
                to=recipient.phone,
                variables=recipient.variables_json,
            )
            recipient.status = "sent"
            recipient.sent_at = result.get("sent_at")
            recipient.provider_message_id = result.get("provider_message_id")
            logger.info("[CAMPAIGN RECIPIENT SENT] campaign_id=%s recipient_id=%s provider_message_id=%s", campaign.id, recipient.id, recipient.provider_message_id)
        except Exception as exc:
            recipient.status = "failed"
            recipient.failed_at = datetime.utcnow()
            recipient.error_message = str(exc)[:1000]
            logger.error("[CAMPAIGN RECIPIENT FAILED] campaign_id=%s recipient_id=%s error=%s", campaign.id, recipient.id, recipient.error_message)
        _refresh_campaign_metrics(db, campaign)
        time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
        db.commit()
