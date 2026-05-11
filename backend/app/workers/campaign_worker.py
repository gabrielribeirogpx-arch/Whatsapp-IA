from __future__ import annotations

import logging
import os
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

RATE_PER_SEC = int(os.getenv("CAMPAIGN_RATE_PER_SECOND", "8"))
CHUNK_SIZE = int(os.getenv("CAMPAIGN_CHUNK_SIZE", "200"))


def process_campaign(campaign_id: str) -> None:
    redis_conn = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    lock_key = f"campaign:lock:{campaign_id}"
    if not redis_conn.set(lock_key, "1", ex=900, nx=True):
        logger.warning("campaign already running campaign_id=%s", campaign_id)
        return

    try:
        with SessionLocal() as db:
            campaign = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id)).scalars().first()
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
                queue.enqueue("app.workers.campaign_worker.process_campaign_recipient", str(rec.id), retry=Retry(max=3, interval=[5, 20, 60]), job_timeout=120)
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
            campaign.total_sent = int(campaign.total_sent or 0) + 1
        except Exception as exc:
            recipient.status = "failed"
            recipient.failed_at = datetime.utcnow()
            recipient.error_message = str(exc)[:1000]
            campaign.total_failed = int(campaign.total_failed or 0) + 1
        campaign.total_recipients = db.execute(select(func.count(WhatsAppCampaignRecipient.id)).where(WhatsAppCampaignRecipient.campaign_id == campaign.id)).scalar() or 0
        if RATE_PER_SEC > 0:
            time.sleep(1 / RATE_PER_SEC)
        db.commit()
