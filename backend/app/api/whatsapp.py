from fastapi import APIRouter, Request

from app.core.whatsapp_config import WHATSAPP_VERIFY_TOKEN
from app.services.flow_engine import run_flow_from_message
from app.services.intent_service import classify_intent, route_intent
from app.services.whatsapp_service import send_whatsapp_message_simple

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params

    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN:
        return int(params.get("hub.challenge"))

    return {"error": "Verification failed"}


@router.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    print("INCOMING WEBHOOK:", data)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" not in value:
            return {"status": "no message"}

        message = value["messages"][0]
        phone = message["from"]
        if message.get("type") == "text":
            text = message.get("text", {}).get("body", "")
        else:
            text = ""

        print("USER:", phone)
        print("[USER INPUT]:", text)
        intent = classify_intent(text)
        print("[INTENT]:", intent)

        response = run_flow_from_message(phone, text)
        print("FLOW RESPONSE:", response)

        messages = response.get("messages") if isinstance(response, dict) else None
        if messages:
            for msg in messages:
                send_whatsapp_message_simple(phone, msg["content"])
        else:
            send_whatsapp_message_simple(phone, route_intent(intent))

    except Exception as e:
        print("ERROR:", str(e))

    return {"status": "ok"}
