import os

from fastapi import APIRouter, Query, Request

from app.services.webhook_ingress import enqueue_webhook_payload

router = APIRouter()


@router.get("/webhook/whatsapp")
def verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    mode = hub_mode
    challenge = hub_challenge
    verify_token = hub_verify_token

    if mode == "subscribe" and verify_token == os.getenv("WHATSAPP_VERIFY_TOKEN"):
        return int(challenge or "0")

    return {"error": "invalid"}


@router.post("/webhook/whatsapp")
async def receive(request: Request):
    # Alias legado para integradores antigos.
    # Mesmo princípio do endpoint canônico: ACK imediato + enqueue assíncrono.
    enqueued, _ = await enqueue_webhook_payload(request)
    return {"status": "queued" if enqueued else "accepted"}
