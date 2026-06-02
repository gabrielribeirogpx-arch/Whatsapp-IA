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
