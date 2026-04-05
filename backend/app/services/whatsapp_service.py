import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class WhatsAppConfigError(RuntimeError):
    """Erro de configuração para integração com WhatsApp Cloud API."""


def enviar_mensagem(numero: str, mensagem: str) -> dict[str, Any]:
    """Envia uma mensagem de texto para um número via WhatsApp Cloud API."""
    token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID")

    if not token or not phone_number_id:
        missing_vars = [
            name
            for name, value in {
                "WHATSAPP_TOKEN": token,
                "PHONE_NUMBER_ID": phone_number_id,
            }.items()
            if not value
        ]
        missing = ", ".join(missing_vars)
        raise WhatsAppConfigError(
            f"Variáveis de ambiente obrigatórias ausentes: {missing}"
        )

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem},
    }

    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            logger.info("Mensagem enviada para %s", numero)
            return response_data
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.exception(
            "Erro HTTP ao enviar mensagem para %s. status=%s body=%s",
            numero,
            exc.code,
            error_body,
        )
        raise
    except URLError:
        logger.exception("Erro de conexão ao enviar mensagem para %s", numero)
        raise


def send_whatsapp_message(phone: str, message: str) -> dict[str, Any]:
    """Compatibilidade retroativa com código existente."""
    return enviar_mensagem(phone, message)
