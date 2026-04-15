import logging
import re
from typing import Any

from backend.app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)


def sanitize_text(value: str) -> str:
    sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
    return sanitized.strip()


def sanitize_phone(value: str) -> str:
    return normalize_phone(value)


def extract_whatsapp_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages_data: list[dict[str, str]] = []
    entries = payload.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = sanitize_text(metadata.get("phone_number_id", ""))

            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            fallback_phone = ""
            fallback_name = "Cliente"
            if contacts:
                fallback_phone = contacts[0].get("wa_id", "")
                fallback_name = contacts[0].get("profile", {}).get("name", "Cliente")

            for message in messages:
                if message.get("type") != "text":
                    continue

                phone = sanitize_phone(message.get("from") or fallback_phone)
                text = sanitize_text(message.get("text", {}).get("body", ""))
                message_id = sanitize_text(message.get("id", ""))
                if not phone or not text:
                    continue

                messages_data.append(
                    {
                        "phone": phone,
                        "text": text,
                        "message_id": message_id,
                        "name": sanitize_text(fallback_name) or "Cliente",
                        "phone_number_id": phone_number_id,
                    }
                )

    return messages_data
