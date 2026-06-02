from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.services.message_service import normalize_meta_message


def test_normalize_meta_message_preserves_interactive_list_reply_metadata():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "123"},
                            "contacts": [{"wa_id": "5511999990000", "profile": {"name": "Cliente"}}],
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": "5511999990000",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {
                                            "id": "atendimento_via_whatsapp",
                                            "title": "Atendimento via WhatsApp",
                                        },
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    [message] = normalize_meta_message(payload)

    assert message["text"] == "atendimento_via_whatsapp"
    assert message["interactive_type"] == "list_reply"
    assert message["selected_row_id"] == "atendimento_via_whatsapp"
    assert message["selected_title"] == "Atendimento via WhatsApp"


def test_normalize_meta_message_logs_interactive_list_diagnostics(caplog):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "123"},
                            "contacts": [{"wa_id": "5511999990000", "profile": {"name": "Cliente"}}],
                            "messages": [
                                {
                                    "id": "wamid.2",
                                    "from": "5511999990000",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {
                                            "id": "opcao_1",
                                            "title": "Opção 1",
                                        },
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with caplog.at_level("INFO"):
        [message] = normalize_meta_message(payload)

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "[META RAW MESSAGE]" in log_text
    assert "[MESSAGE TYPE DETECTED]" in log_text
    assert "[INTERACTIVE LIST DETECTED]" in log_text
    assert "[INTERACTIVE LIST PARSED]" in log_text
    assert "[MESSAGE NORMALIZED]" in log_text
    assert "message.type=interactive" in log_text
    assert "interactive.type=list_reply" in log_text
    assert "interactive.list_reply.id=opcao_1" in log_text
    assert "interactive.list_reply.title=Opção 1" in log_text
    assert message["selected_row_id"] == "opcao_1"


def test_pick_message_accepts_direct_interactive_list_reply_without_text(monkeypatch):
    from app.workers import message_worker

    monkeypatch.setattr(message_worker, "normalize_meta_message", lambda payload: [])

    parsed = message_worker._pick_message(
        {
            "phone": "5511999990000",
            "message_id": "wamid.direct",
            "phone_number_id": "123",
            "interactive_type": "list_reply",
            "selected_row_id": "opcao_2",
            "selected_title": "Opção 2",
        }
    )

    assert parsed is not None
    assert parsed["type"] == "interactive"
    assert parsed["text"] == "opcao_2"
    assert parsed["interactive_type"] == "list_reply"
    assert parsed["selected_row_id"] == "opcao_2"
