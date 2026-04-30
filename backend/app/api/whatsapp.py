from fastapi import APIRouter, Request

from app.core.whatsapp_config import WHATSAPP_VERIFY_TOKEN
from app.services.flow_engine import run_flow_from_message
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
        text = message["text"]["body"]

        print("USER:", phone)
        print("MESSAGE:", text)

        response = run_flow_from_message(phone, text)
        print("FLOW RESPONSE:", response)

        for msg in response["messages"]:
            send_whatsapp_message_simple(phone, msg["content"])

    except Exception as e:
        print("ERROR:", str(e))

    return {"status": "ok"}
