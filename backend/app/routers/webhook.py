import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database import get_db
from backend.app.models import Conversation, Message
from backend.app.services.message_service import extract_whatsapp_messages
from backend.app.services.realtime_service import sse_broker
from backend.app.services.tenant_service import (
    get_or_create_default_tenant,
    get_tenant_by_phone_number_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


def _channel(tenant_id: int, phone: str) -> str:
    return f"{tenant_id}:{phone}"


def generate_response() -> str:
    return "Recebi sua mensagem 🚀"


def send_whatsapp_message(to: str, message: str, phone_number_id: str):
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    logger.info("Enviando resposta automática para %s via phone_number_id=%s", to, phone_number_id)
    response = requests.post(url, headers=headers, json=data, timeout=15)
    response.raise_for_status()
    logger.info("Resposta automática enviada com sucesso para %s (status=%s)", to, response.status_code)


@router.get("/webhook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.verify_token and challenge:
        return int(challenge)

    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
        print("Payload recebido:", payload)
    except Exception as e:
        print("Erro ao ler JSON:", str(e))
        payload = {}

    return {"status": "ok"}
