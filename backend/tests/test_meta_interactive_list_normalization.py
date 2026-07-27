from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.services.message_service import normalize_meta_message
from app.services.webhook_ingress import _log_interactive_ingress


def _interactive_payload(reply_type, reply_id, title):
    return {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "123"},
            "contacts": [{"wa_id": "5511999990000", "profile": {"name": "Cliente"}}],
            "messages": [{
                "id": f"wamid.{reply_id}", "from": "5511999990000", "type": "interactive",
                "interactive": {"type": reply_type, reply_type: {"id": reply_id, "title": title}},
            }],
        }}]}],
    }


def test_button_reply_preserves_stable_id_as_runtime_selection():
    [message] = normalize_meta_message(_interactive_payload("button_reply", "comercial", "Comercial"))

    assert message == {
        "phone": "5511999990000", "text": "comercial", "type": "interactive",
        "tenant_id": None, "phone_number_id": "123", "name": "Cliente",
        "message_id": "wamid.comercial", "interactive_type": "button_reply",
        "interactive_reply_id": "comercial", "interactive_reply_title": "Comercial",
        "selected_row_id": "comercial", "selected_title": "Comercial",
    }


def test_button_reply_pipeline_log_exposes_canonical_choice_key(caplog):
    with caplog.at_level("INFO"):
        normalize_meta_message(_interactive_payload("button_reply", "comercial", "Comercial"))

    pipeline_log = next(
        record.getMessage()
        for record in caplog.records
        if "stage=normalize_meta_message" in record.getMessage()
    )
    assert "message.type=interactive" in pipeline_log
    assert "interactive.type=button_reply" in pipeline_log
    assert "button_reply.id=comercial" in pipeline_log
    assert "interactive_reply_id=comercial" in pipeline_log
    assert "selected_row_id=comercial" in pipeline_log
    assert "row_id=comercial" in pipeline_log
    assert "runtime_choice_key=comercial" in pipeline_log


def test_webhook_ingress_logs_button_reply_identity_without_message_body(caplog):
    payload = _interactive_payload("button_reply", "comercial", "Comercial")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"] = {
        "body": "conteudo privado"
    }

    with caplog.at_level("INFO"):
        _log_interactive_ingress(payload, correlation_id="wamid.comercial")

    ingress_log = next(
        record.getMessage()
        for record in caplog.records
        if "stage=webhook_received" in record.getMessage()
    )
    assert "message.type=interactive" in ingress_log
    assert "interactive.type=button_reply" in ingress_log
    assert "button_reply.id=comercial" in ingress_log
    assert "interactive_reply_id=comercial" in ingress_log
    assert "selected_row_id=comercial" in ingress_log
    assert "row_id=comercial" in ingress_log
    assert "runtime_choice_key=comercial" in ingress_log
    assert "conteudo privado" not in ingress_log


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


def test_pick_message_logs_normalize_output_and_raw_payload(caplog):
    from app.workers import message_worker

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
                                    "id": "wamid.3",
                                    "from": "5511999990000",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {"id": "opcao_3", "title": "Opção 3"},
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
        parsed = message_worker._pick_message(payload)

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "[META WORKER RAW PAYLOAD]" in log_text
    assert "[NORMALIZE_META_MESSAGE INPUT]" in log_text
    assert "[NORMALIZE_META_MESSAGE COMPLETE] count=1" in log_text
    assert "[NORMALIZE_META_MESSAGE OUTPUT] count=1 payload_shape=entry_count=1 message_count=1" in log_text
    assert '"selected_row_id": "opcao_3"' in log_text
    assert parsed is not None
    assert parsed["selected_row_id"] == "opcao_3"


def test_pick_message_logs_unsupported_parse_reason(caplog, monkeypatch):
    from app.workers import message_worker

    monkeypatch.setattr(message_worker, "normalize_meta_message", lambda payload: [])

    with caplog.at_level("WARNING"):
        parsed = message_worker._pick_message({"entry": [], "message_id": "wamid.empty"})

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert parsed is None
    assert "[MESSAGE PARSE UNSUPPORTED] reason=no_supported_message" in log_text
    assert "payload_shape=entry_count=0 message_count=0" in log_text


class _DummyWebhookRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_enqueue_webhook_payload_logs_complete_meta_payload(caplog, monkeypatch):
    from app.services import webhook_ingress

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "123"},
                            "messages": [
                                {
                                    "id": "wamid.raw",
                                    "from": "5511999990000",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {"id": "opcao_raw", "title": "Opção raw"},
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(webhook_ingress, "_update_campaign_status_from_meta", lambda payload: None)
    monkeypatch.setattr(webhook_ingress, "_resolve_inbound_tenant", lambda db, payload: webhook_ingress.InboundTenantResolution("tenant-raw", "provider-raw", "123"))
    class _Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(webhook_ingress, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(webhook_ingress, "enqueue_incoming_message", lambda payload: "job-raw")

    import asyncio

    with caplog.at_level("INFO"):
        enqueued, correlation_id = asyncio.run(webhook_ingress.enqueue_webhook_payload(_DummyWebhookRequest(payload)))

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert enqueued is True
    assert correlation_id == "wamid.raw"
    assert "[META WEBHOOK PAYLOAD]" in log_text
    assert '"id": "opcao_raw"' in log_text
    assert "stage=webhook_received" in log_text
    assert "message.type=interactive" in log_text
    assert "interactive.type=list_reply" in log_text
    assert "raw_payload=" in log_text


def test_enqueue_webhook_payload_resolves_known_provider_before_enqueue(caplog, monkeypatch):
    from app.services import webhook_ingress

    payload = {
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "123"}, "messages": [{"id": "wamid.known", "from": "5511999990000", "type": "text", "text": {"body": "Oi"}}]}}]}]
    }
    enqueued_payloads = []
    monkeypatch.setattr(webhook_ingress, "_update_campaign_status_from_meta", lambda payload: None)
    monkeypatch.setattr(
        webhook_ingress,
        "_resolve_inbound_tenant",
        lambda db, payload: webhook_ingress.InboundTenantResolution("tenant-1", "provider-1", "123"),
    )
    monkeypatch.setattr(webhook_ingress, "enqueue_incoming_message", lambda payload: enqueued_payloads.append(dict(payload)) or "job-1")

    class _Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(webhook_ingress, "SessionLocal", lambda: _Session())

    import asyncio

    with caplog.at_level("INFO"):
        enqueued, correlation_id = asyncio.run(webhook_ingress.enqueue_webhook_payload(_DummyWebhookRequest(payload)))

    assert enqueued is True
    assert correlation_id == "wamid.known"
    assert enqueued_payloads[0]["tenant_id"] == "tenant-1"
    assert enqueued_payloads[0]["provider_id"] == "provider-1"
    assert enqueued_payloads[0]["phone_number_id"] == "123"
    assert enqueued_payloads[0]["correlation_id"] == "wamid.known"
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=inbound_enqueued" in log_text
    assert "tenant_id=tenant-1" in log_text


def test_enqueue_webhook_payload_unknown_provider_does_not_enqueue(caplog, monkeypatch):
    from app.services import webhook_ingress

    payload = {
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "404"}, "messages": [{"id": "wamid.unknown", "from": "5511999990000", "type": "text", "text": {"body": "Oi"}}]}}]}]
    }
    calls = []
    monkeypatch.setattr(webhook_ingress, "_update_campaign_status_from_meta", lambda payload: None)
    monkeypatch.setattr(
        webhook_ingress,
        "_resolve_inbound_tenant",
        lambda db, payload: webhook_ingress.InboundTenantResolution(None, None, "404", "provider_not_found"),
    )
    monkeypatch.setattr(webhook_ingress, "enqueue_incoming_message", lambda payload: calls.append(payload) or "job-should-not-run")

    class _Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(webhook_ingress, "SessionLocal", lambda: _Session())

    import asyncio

    with caplog.at_level("WARNING"):
        enqueued, correlation_id = asyncio.run(webhook_ingress.enqueue_webhook_payload(_DummyWebhookRequest(payload)))

    assert enqueued is False
    assert correlation_id == "wamid.unknown"
    assert calls == []
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=inbound_tenant_resolution_failed" in log_text
    assert "phone_number_id=404" in log_text
    assert "reason=provider_not_found" in log_text
