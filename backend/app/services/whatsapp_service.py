import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


class WhatsAppConfigError(RuntimeError):
    """Erro de configuração para integração com WhatsApp Cloud API."""


def send_message(token: str, phone_id: str, to: str, message: str) -> dict[str, Any]:
    """Envia uma mensagem usando a API oficial do WhatsApp Cloud."""
    if not token:
        raise WhatsAppConfigError("WHATSAPP_TOKEN não configurado")
    if not phone_id:
        raise Exception("PHONE_NUMBER_ID não configurado")

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        response_data = response.json()
        logger.info("Mensagem enviada para %s", to)
        return response_data
    except requests.HTTPError:
        logger.exception(
            "Erro HTTP ao enviar mensagem para %s. status=%s body=%s",
            to,
            response.status_code if 'response' in locals() else None,
            response.text if 'response' in locals() else None,
        )
        raise
    except requests.RequestException:
        logger.exception("Erro de conexão ao enviar mensagem para %s", to)
        raise


def enviar_mensagem(
    numero: str,
    mensagem: str,
    *,
    token: str | None = None,
    phone_number_id: str | None = None,
) -> dict[str, Any]:
    token = token or os.getenv("WHATSAPP_TOKEN")
    phone_number_id = phone_number_id or os.getenv("PHONE_NUMBER_ID")
    return send_message(token or "", phone_number_id or "", numero, mensagem)


def send_whatsapp_message(phone: str, message: str) -> dict[str, Any]:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID")
    return send_message(token or "", phone_number_id or "", phone, message)
