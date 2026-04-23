import logging
import os
import re
from typing import Any

import requests

from app.models import Tenant

logger = logging.getLogger(__name__)


class WhatsAppConfigError(RuntimeError):
    """Erro de configuração para integração com WhatsApp Cloud API."""


def send_message(token: str, phone_number_id: str, to: str, message: str) -> dict[str, Any]:
    """Envia uma mensagem usando a API oficial do WhatsApp Cloud."""
    if not token:
        raise WhatsAppConfigError("WHATSAPP_TOKEN não configurado")
    if not phone_number_id:
        raise WhatsAppConfigError("PHONE_NUMBER_ID do tenant não configurado")

    normalized_phone = re.sub(r"\D", "", to or "")
    if not normalized_phone:
        raise WhatsAppConfigError("Telefone de destino inválido")

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
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
        if response.status_code != 200:
            print("[META ERROR]", response.text)
        response.raise_for_status()
        response_data = response.json()
        logger.info(
            "Mensagem enviada para %s com phone_number_id=%s response=%s",
            normalized_phone,
            phone_number_id,
            response_data,
        )
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


def enviar_mensagem(numero: str, mensagem: str, *, token: str | None = None, phone_number_id: str | None = None) -> dict[str, Any]:
    token = token or os.getenv("WHATSAPP_TOKEN")
    resolved_phone_number_id = phone_number_id or os.getenv("PHONE_NUMBER_ID")
    return send_message(token or "", resolved_phone_number_id or "", numero, mensagem)


def send_whatsapp_message(tenant: Tenant, phone: str, text: str) -> dict[str, Any]:
    if not tenant.whatsapp_token:
        raise WhatsAppConfigError("tenant.whatsapp_token ausente")
    if not tenant.phone_number_id:
        raise WhatsAppConfigError("tenant.phone_number_id ausente")

    normalized_phone = re.sub(r"\D", "", phone or "")
    if not normalized_phone:
        raise WhatsAppConfigError("phone inválido para envio")

    return send_message(
        token=tenant.whatsapp_token,
        phone_number_id=tenant.phone_number_id,
        to=normalized_phone,
        message=text,
    )
