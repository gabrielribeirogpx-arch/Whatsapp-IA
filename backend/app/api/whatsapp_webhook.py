import os

from fastapi import APIRouter, Query, Request

from app.services.flow_runtime_queue import enqueue_flow_job

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
    body = await request.json()

    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        messages = value.get("messages")

        if not messages:
            return {"status": "no message"}

        message = messages[0]

        phone = message["from"]
        text = message["text"]["body"]
        message_id = message["id"]

        conversation_id = phone
        flow_id = os.getenv("DEFAULT_FLOW_ID", "")

        enqueue_flow_job(
            flow_id=flow_id,
            conversation_id=conversation_id,
            message=text,
            message_id=message_id,
        )

        return {"status": "queued"}

    except Exception as e:
        print("[WEBHOOK ERROR]", str(e))
        return {"status": "error"}
