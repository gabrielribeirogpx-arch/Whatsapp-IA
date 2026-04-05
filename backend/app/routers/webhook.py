import json
import logging
import os

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
async def verify(request: Request):
    verify_token = os.getenv("VERIFY_TOKEN")

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == verify_token:
        return int(challenge)

    return {"error": "verification failed"}


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    logger.info("📩 Evento recebido do WhatsApp:")
    logger.info(json.dumps(payload, indent=2, ensure_ascii=False))
    return {"status": "received"}
