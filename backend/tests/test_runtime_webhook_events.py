import asyncio

from app.routers import webhook
from app.services.flow_runtime_service import execute_node_chain_until_reply


def test_runtime_emits_events_in_order_for_message_delay_message(monkeypatch):
    sleep_calls = []

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.flow_runtime_service.asyncio.sleep", _fake_sleep)

    graph = {
        "nodes": [
            {"id": "n1", "type": "message", "data": {"text": "Boa!"}},
            {"id": "n2", "type": "delay", "data": {"seconds": 2}},
            {"id": "n3", "type": "message", "data": {"text": "O Wazza API é..."}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }

    result = asyncio.run(execute_node_chain_until_reply(
        graph=graph,
        start_node_id="n1",
        user_input="qualquer",
    ))

    assert result["events"] == [
        {"type": "send_message", "text": "Boa!"},
        {"type": "delay", "seconds": 2},
        {"type": "send_message", "text": "O Wazza API é..."},
    ]
    assert sleep_calls == [2]


def test_webhook_process_runtime_events_sends_two_separate_messages(monkeypatch):
    sent_messages = []
    sleep_calls = []

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    def _fake_send(phone: str, text: str):
        sent_messages.append((phone, text))

    monkeypatch.setattr(webhook.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(webhook, "send_whatsapp_message_simple", _fake_send)

    should_pause = asyncio.run(webhook._process_runtime_events(
        events=[
            {"type": "send_message", "text": "Boa!"},
            {"type": "delay", "seconds": 2},
            {"type": "send_message", "text": "O Wazza API é..."},
        ],
        phone="5511999999999",
        execution=None,
        tenant_uuid="00000000-0000-0000-0000-000000000001",
        wa_id="wa-123",
        db=None,
    ))

    assert should_pause is False
    assert sleep_calls == [2]
    assert sent_messages == [
        ("5511999999999", "Boa!"),
        ("5511999999999", "O Wazza API é..."),
    ]
    assert all("Boa! O Wazza API é..." not in text for _, text in sent_messages)
