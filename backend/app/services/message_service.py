import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_response(message: str) -> str:
    return "Recebi sua mensagem"


def extract_whatsapp_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages_data: list[dict[str, str]] = []
    entries = payload.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            fallback_phone = ""
            if contacts:
                fallback_phone = contacts[0].get("wa_id", "")

            for message in messages:
                phone = message.get("from") or fallback_phone
                text = message.get("text", {}).get("body")
                if not phone or not text:
                    continue

                messages_data.append({"phone": phone, "text": text})

    return messages_data


def process_message(payload: dict[str, Any]) -> list[dict[str, str]]:
    extracted_messages = extract_whatsapp_messages(payload)

    for message in extracted_messages:
        logger.info(
            "Mensagem recebida. phone=%s text=%s",
            message["phone"],
            message["text"],
        )

    return extracted_messages
