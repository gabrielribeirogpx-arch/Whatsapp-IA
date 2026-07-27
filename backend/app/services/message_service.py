import json
import logging
import re
from typing import Any

from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)


def _json_log_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(payload)


def _interactive_debug_fields(message: dict[str, Any]) -> dict[str, str]:
    interactive = message.get("interactive") if isinstance(message.get("interactive"), dict) else {}
    button_reply = interactive.get("button_reply") if isinstance(interactive.get("button_reply"), dict) else {}
    list_reply = interactive.get("list_reply") if isinstance(interactive.get("list_reply"), dict) else {}
    interactive_type = sanitize_text(str(interactive.get("type") or ""))
    button_reply_id = sanitize_text(str(button_reply.get("id") or ""))
    button_reply_title = sanitize_text(str(button_reply.get("title") or ""))
    list_reply_id = sanitize_text(str(list_reply.get("id") or ""))
    list_reply_title = sanitize_text(str(list_reply.get("title") or ""))
    return {
        "message_type": sanitize_text(str(message.get("type") or "")),
        "interactive_type": interactive_type,
        "interactive_button_reply_id": button_reply_id,
        "interactive_button_reply_title": button_reply_title,
        "interactive_list_reply_id": list_reply_id,
        "interactive_list_reply_title": list_reply_title,
        "selected_row_id": list_reply_id if interactive_type == "list_reply" else "",
    }


def _log_meta_message_marker(marker: str, *, message: dict[str, Any], payload: Any | None = None) -> None:
    fields = _interactive_debug_fields(message)
    logger.info(
        "%s message.type=%s interactive.type=%s interactive.button_reply.id=%s interactive.button_reply.title=%s interactive.list_reply.id=%s interactive.list_reply.title=%s selected_row_id=%s payload=%s",
        marker,
        fields["message_type"] or "n/a",
        fields["interactive_type"] or "n/a",
        fields["interactive_button_reply_id"] or "n/a",
        fields["interactive_button_reply_title"] or "n/a",
        fields["interactive_list_reply_id"] or "n/a",
        fields["interactive_list_reply_title"] or "n/a",
        fields["selected_row_id"] or "n/a",
        _json_log_payload(message if payload is None else payload),
    )


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


def normalize_meta_message(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    logger.info("[NORMALIZE_META_MESSAGE INPUT] payload=%s", _json_log_payload(payload))
    normalized: list[dict[str, str | None]] = []
    entries = payload.get("entry", [])

    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = sanitize_text(metadata.get("phone_number_id", ""))
            contacts = value.get("contacts", [])
            fallback_phone = sanitize_phone(contacts[0].get("wa_id", "")) if contacts else ""

            for message in value.get("messages", []):
                _log_meta_message_marker("[META RAW MESSAGE]", message=message)
                message_type = sanitize_text(str(message.get("type", "")))
                text = ""
                interactive_type = ""
                interactive_reply_id = ""
                interactive_reply_title = ""
                _log_meta_message_marker("[MESSAGE TYPE DETECTED]", message=message)
                if message_type == "interactive":
                    _log_meta_message_marker("[CHOICE WEBHOOK RECEIVED]", message=message)
                if message_type == "text":
                    text = sanitize_text(str(message.get("text", {}).get("body", "")))
                elif message_type == "interactive":
                    interactive = message.get("interactive", {}) if isinstance(message.get("interactive"), dict) else {}
                    interactive_type = sanitize_text(str(interactive.get("type", "")))
                    if interactive_type == "button_reply":
                        reply = interactive.get("button_reply", {}) if isinstance(interactive.get("button_reply"), dict) else {}
                        interactive_reply_id = sanitize_text(str(reply.get("id", "")))
                        interactive_reply_title = sanitize_text(str(reply.get("title", "")))
                        text = interactive_reply_id
                    elif interactive_type == "list_reply":
                        _log_meta_message_marker("[INTERACTIVE LIST DETECTED]", message=message)
                        reply = interactive.get("list_reply", {}) if isinstance(interactive.get("list_reply"), dict) else {}
                        interactive_reply_id = sanitize_text(str(reply.get("id", "")))
                        interactive_reply_title = sanitize_text(str(reply.get("title", "")))
                        text = interactive_reply_id
                        _log_meta_message_marker("[INTERACTIVE LIST PARSED]", message=message)

                phone = sanitize_phone(message.get("from", "") or fallback_phone)
                if not phone:
                    continue

                normalized_message = {
                    "phone": phone,
                    "text": text,
                    "type": message_type or "unknown",
                    "tenant_id": None,
                    "phone_number_id": phone_number_id,
                    "name": sanitize_text(str(contacts[0].get("profile", {}).get("name", ""))) if contacts else "",
                    "message_id": sanitize_text(str(message.get("id", ""))),
                    "interactive_type": interactive_type or None,
                    "interactive_reply_id": interactive_reply_id or None,
                    "interactive_reply_title": interactive_reply_title or None,
                    # Both WhatsApp reply kinds carry stable IDs.  Keep one
                    # provider-neutral alias all the way to Runtime V2.
                    "selected_row_id": interactive_reply_id or None,
                    "selected_title": interactive_reply_title or None,
                }
                if message_type == "interactive":
                    _log_meta_message_marker("[CHOICE PARSED]", message=message, payload=normalized_message)
                _log_meta_message_marker("[MESSAGE NORMALIZED]", message=message, payload=normalized_message)
                normalized.append(normalized_message)

    logger.info("[NORMALIZE_META_MESSAGE COMPLETE] count=%s normalized=%s", len(normalized), _json_log_payload(normalized))
    return normalized
