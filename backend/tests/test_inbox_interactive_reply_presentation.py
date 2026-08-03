from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.models.message import Message
from app.schemas.chat import MessageOut
from app.services.message_service import normalize_meta_message


def _message(*, payload: str, title: str | None) -> Message:
    return Message(
        id=uuid4(),
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        text=payload,
        interactive_title=title,
        from_me=False,
        created_at=datetime(2026, 8, 3),
    )


def test_button_reply_title_is_displayed_while_id_remains_debuggable():
    output = MessageOut.model_validate(
        _message(payload="quero_planos", title="Agendar avaliação")
    )

    assert output.content == "Agendar avaliação"
    assert output.technical_payload == "quero_planos"


def test_list_reply_title_is_displayed_while_id_remains_persisted():
    message = _message(payload="implante", title="Implante")

    assert message.text == "implante"
    assert message.content == "Implante"
    assert message.technical_payload == "implante"


def test_historical_message_without_title_falls_back_to_existing_text():
    output = MessageOut.model_validate(
        _message(payload="quero_planos", title=None)
    )

    assert output.content == "quero_planos"
    assert output.technical_payload is None


def test_interactive_title_priority_supports_generic_provider_title():
    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "123"},
            "contacts": [{"wa_id": "5511999990000"}],
            "messages": [{
                "id": "wamid.priority",
                "from": "5511999990000",
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "title": "Título genérico",
                    "button_reply": {"id": "payload", "title": "Título do botão"},
                    "list_reply": {"id": "ignored", "title": "Título da lista"},
                },
            }],
        }}]}],
    }

    [normalized] = normalize_meta_message(payload)

    assert normalized["text"] == "payload"
    assert normalized["interactive_reply_title"] == "Título do botão"


def test_interactive_generic_title_is_used_when_reply_title_is_missing():
    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "123"},
            "contacts": [{"wa_id": "5511999990000"}],
            "messages": [{
                "id": "wamid.generic",
                "from": "5511999990000",
                "type": "interactive",
                "interactive": {
                    "type": "list_reply",
                    "title": "Título legado",
                    "list_reply": {"id": "payload_legado"},
                },
            }],
        }}]}],
    }

    [normalized] = normalize_meta_message(payload)

    assert normalized["text"] == "payload_legado"
    assert normalized["interactive_reply_title"] == "Título legado"
