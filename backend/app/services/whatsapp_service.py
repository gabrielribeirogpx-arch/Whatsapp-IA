import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class WhatsAppConfigError(RuntimeError):
    """Erro de configuração para integração com WhatsApp Cloud API."""


def send_message(token: str, phone_id: str, to: str, message: str) -> dict[str, Any]:
    """Envia uma mensagem usando a API oficial do WhatsApp Cloud."""
    if not token or not phone_id:
        missing_vars = [name for name, value in {"WHATSAPP_TOKEN": token, "PHONE_NUMBER_ID": phone_id}.items() if not value]
        raise WhatsAppConfigError(f"Variáveis de configuração obrigatórias ausentes: {', '.join(missing_vars)}")

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            logger.info("Mensagem enviada para %s", to)
            return response_data
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.exception("Erro HTTP ao enviar mensagem para %s. status=%s body=%s", to, exc.code, error_body)
        raise
    except URLError:
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
    return enviar_mensagem(phone, message)
