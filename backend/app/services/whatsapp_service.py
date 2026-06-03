import logging
import re
from typing import Any

import requests

from app.services.whatsapp_credentials_service import get_tenant_whatsapp_credentials
from app.services.message_origin_trace import log_message_origin_trace

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
    log_message_origin_trace(
        executor="whatsapp_service.send_message",
        message=message,
    )
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

    log_message_origin_trace(
        executor="whatsapp_service.send_whatsapp_interactive_buttons",
        message=body_text,
        node_type="interactive_buttons",
    )
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


def _post_cloud_message(*, phone: str, token: str, phone_number_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not token:
        raise WhatsAppConfigError("WHATSAPP_TOKEN não configurado")
    if not phone_number_id:
        raise WhatsAppConfigError("PHONE_NUMBER_ID do tenant não configurado")
    normalized_phone = re.sub(r"\D", "", phone or "")
    if not normalized_phone:
        raise WhatsAppConfigError("Telefone de destino inválido")

    message_preview = ""
    if payload.get("type") == "image":
        message_preview = (payload.get("image") or {}).get("caption") or (payload.get("image") or {}).get("link") or ""
    elif payload.get("type") == "document":
        message_preview = (payload.get("document") or {}).get("caption") or (payload.get("document") or {}).get("filename") or (payload.get("document") or {}).get("link") or ""
    elif payload.get("type") == "interactive":
        message_preview = ((payload.get("interactive") or {}).get("body") or {}).get("text") or ""
    log_message_origin_trace(
        executor="whatsapp_service._post_cloud_message",
        node_type=payload.get("type"),
        message=message_preview,
    )
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {**payload, "messaging_product": "whatsapp", "to": normalized_phone}
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
        return response.json()
    except requests.HTTPError:
        logger.exception(
            "Erro HTTP ao enviar rich message para %s. status=%s body=%s",
            phone,
            response.status_code if 'response' in locals() else None,
            response.text if 'response' in locals() else None,
        )
        raise
    except requests.RequestException:
        logger.exception("Erro de conexão ao enviar rich message para %s", phone)
        raise


def send_whatsapp_image(*, phone: str, media_url: str, caption: str = "", token: str, phone_number_id: str) -> dict[str, Any]:
    return _post_cloud_message(
        phone=phone,
        token=token,
        phone_number_id=phone_number_id,
        payload={"type": "image", "image": {"link": media_url, **({"caption": caption} if caption else {})}},
    )


def send_whatsapp_document(*, phone: str, document_url: str, filename: str = "", caption: str = "", token: str, phone_number_id: str) -> dict[str, Any]:
    document: dict[str, Any] = {"link": document_url}
    if filename:
        document["filename"] = filename
    if caption:
        document["caption"] = caption
    return _post_cloud_message(
        phone=phone,
        token=token,
        phone_number_id=phone_number_id,
        payload={"type": "document", "document": document},
    )


def send_whatsapp_interactive_list(*, phone: str, body_text: str, sections: list[dict], token: str, phone_number_id: str, button_text: str = "Ver opções") -> dict[str, Any]:
    safe_sections: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections or []):
        if not isinstance(section, dict):
            continue
        rows = []
        for row_index, row in enumerate(section.get("rows") or []):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("label") or "").strip()[:24]
            if not title:
                continue
            rows.append({
                "id": str(row.get("id") or row.get("handleId") or f"row_{section_index + 1}_{row_index + 1}"),
                "title": title,
                **({"description": str(row.get("description"))[:72]} if row.get("description") else {}),
            })
        if rows:
            safe_sections.append({"title": str(section.get("title") or f"Seção {section_index + 1}")[:24], "rows": rows})
    if not safe_sections:
        return send_whatsapp_message(phone=phone, text=body_text, token=token, phone_number_id=phone_number_id)
    return _post_cloud_message(
        phone=phone,
        token=token,
        phone_number_id=phone_number_id,
        payload={
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {"button": button_text[:20] or "Ver opções", "sections": safe_sections},
            },
        },
    )


def send_whatsapp_message_cloud(phone: str, text: str, *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_message(phone=phone, text=text, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_message_simple(to: str, text: str, *, tenant_id: str):
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_message(phone=to, text=text, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_image_cloud(phone: str, media_url: str, caption: str = "", *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_image(phone=phone, media_url=media_url, caption=caption, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_document_cloud(phone: str, document_url: str, filename: str = "", caption: str = "", *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_document(phone=phone, document_url=document_url, filename=filename, caption=caption, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


def send_whatsapp_list_cloud(phone: str, body_text: str, sections: list[dict], *, tenant_id: str) -> dict[str, Any]:
    credentials = get_tenant_whatsapp_credentials(tenant_id)
    return send_whatsapp_interactive_list(phone=phone, body_text=body_text, sections=sections, token=credentials["token"], phone_number_id=credentials["phone_number_id"])


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
