import logging
import os

from fastapi import APIRouter, Request

from backend.app.services.message_service import generate_response, process_message
from backend.app.services.whatsapp_service import WhatsAppConfigError, send_whatsapp_message

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
    messages = process_message(payload)
    sent_messages = 0

    for item in messages:
        response_text = generate_response(item["text"])
        try:
            send_whatsapp_message(phone=item["phone"], message=response_text)
            sent_messages += 1
        except WhatsAppConfigError as exc:
            logger.warning("Configuração ausente para resposta automática: %s", exc)
            break
        except Exception:
            logger.exception("Erro inesperado ao responder mensagem")

    return {
        "status": "received",
        "messages_received": len(messages),
        "messages_sent": sent_messages,
    }
