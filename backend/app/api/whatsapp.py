from fastapi import APIRouter, Request

from app.core.whatsapp_config import WHATSAPP_VERIFY_TOKEN
from app.services.webhook_ingress import enqueue_webhook_payload

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN:
        return int(params.get("hub.challenge"))

    return {"error": "Verification failed"}


@router.post("/webhook")
async def receive_message(request: Request):
    # Compatibility endpoint retained for provider registrations that still use
    # /api/webhook.  It must share the canonical ingress: the former handler
    # extracted only `text` messages and silently replaced every interactive
    # reply with an empty string before it could reach the worker.
    enqueued, _ = await enqueue_webhook_payload(request)
    return {"status": "queued" if enqueued else "accepted"}
