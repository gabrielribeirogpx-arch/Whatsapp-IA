import logging
import os

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from backend.app.services.message_service import generate_response, process_message
from backend.app.services.whatsapp_service import WhatsAppConfigError, send_whatsapp_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")

    if hub_mode == "subscribe" and verify_token and hub_verify_token == verify_token:
        logger.info("Webhook validado com sucesso")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("Falha na validação do webhook")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Token de verificação inválido",
    )


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
