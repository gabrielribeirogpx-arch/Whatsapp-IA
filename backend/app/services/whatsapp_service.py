import logging
import re
from typing import Any

import requests

from app.services.whatsapp_credentials_service import get_tenant_whatsapp_credentials

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


def enviar_mensagem(numero: str, mensagem: str, *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_message(credentials["token"], credentials["phone_number_id"], numero, mensagem)


def send_whatsapp_message(*, phone: str, text: str, token: str, phone_number_id: str) -> dict[str, Any]:
    normalized_phone = re.sub(r"\D", "", phone or "")
    if not normalized_phone:
        raise WhatsAppConfigError("phone inválido para envio")

    return send_message(
        token=token,
        phone_number_id=phone_number_id,
        to=normalized_phone,
        message=text,
    )


def send_whatsapp_interactive_buttons(
    *,
    phone: str,
    body_text: str,
    buttons: list[dict],
    token: str,
    phone_number_id: str,
) -> dict:
    """
    Envia mensagem com botões interativos (Reply Buttons) via Meta Cloud API.
    Máximo de 3 botões. Cada botão usa id derivado do label e title (máx 20 chars).
    Se não houver botões válidos, faz fallback para mensagem de texto normal.
    """
    normalized_phone = re.sub(r"\D", "", phone or "")
    if not normalized_phone:
        raise WhatsAppConfigError("phone inválido para envio")

    # Limita a 3 botões (limite da Meta) e title a 20 chars
    safe_buttons = [
        {
            "type": "reply",
            "reply": {
                "id": str(btn.get("label") or "").strip().lower(),
                "title": str(btn.get("label") or "")[:20],
            },
        }
        for btn in buttons[:3]
        if isinstance(btn, dict) and str(btn.get("label") or "").strip()
    ]

    if not safe_buttons:
        return send_whatsapp_message(phone=normalized_phone, text=body_text, token=token, phone_number_id=phone_number_id)

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": safe_buttons},
        },
    }

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if response.status_code != 200:
            print("[META BUTTON ERROR]", response.text)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError:
        logger.exception(
            "Erro HTTP ao enviar botões para %s. status=%s body=%s",
            phone,
            response.status_code if "response" in locals() else None,
            response.text if "response" in locals() else None,
        )
        raise
    except requests.RequestException:
        logger.exception("Erro de conexão ao enviar botões para %s", phone)
        raise


def send_whatsapp_message_cloud(phone: str, text: str, *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_message(phone=phone, text=text, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_message_simple(to: str, text: str, *, tenant_id: str):
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_message(phone=to, text=text, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_buttons(phone: str, node: dict[str, Any], *, tenant_id: str):
    buttons = node.get("data", {}).get("buttons", [])

    interactive_buttons = [
        {
            "type": "reply",
            "reply": {
                "id": btn["label"].lower(),
                "title": btn["label"][:20]
            }
        }
        for btn in buttons
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": node.get("data", {}).get("content")
            },
            "action": {
                "buttons": interactive_buttons
            }
        }
    }

    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_interactive_buttons(
        phone=phone,
        body_text=node.get("data", {}).get("content") or "",
        buttons=buttons,
        token=credentials["token"],
        phone_number_id=credentials["phone_number_id"],
    )
