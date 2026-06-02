from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
import types

_stub_flow_engine = types.ModuleType("app.services.flow_engine_service")
_stub_flow_engine.get_flow_for_builder = lambda *args, **kwargs: {}
sys.modules.setdefault("app.services.flow_engine_service", _stub_flow_engine)
_stub_flow_session = types.ModuleType("app.services.flow_session_service")
_stub_flow_session.FlowSessionService = object
sys.modules.setdefault("app.services.flow_session_service", _stub_flow_session)

from app.services import whatsapp_service
from app.services.flow_runtime_service import execute_node_chain_until_reply
from app.services.flow_analytics_service import EVENT_TYPE_ALIASES, BUTTON_CLICKED, LIST_SELECTED


def test_rich_message_runtime_serialization_and_execution():
    graph = {
        "nodes": [
            {"id": "image", "type": "image_node", "data": {"isStart": True, "media_url": "https://cdn.ex/img.png", "caption": "Catálogo"}},
            {"id": "doc", "type": "document_node", "data": {"document_url": "https://cdn.ex/file.pdf", "filename": "file.pdf", "caption": "Contrato"}},
            {"id": "buttons", "type": "buttons_node", "data": {"body_text": "Escolha", "buttons": [{"label": "Vendas", "handleId": "vendas"}, {"label": "Suporte", "handleId": "suporte"}]}},
            {"id": "sales", "type": "message", "data": {"content": "Time comercial"}},
        ],
        "edges": [
            {"source": "image", "target": "doc", "sourceHandle": "default"},
            {"source": "doc", "target": "buttons", "sourceHandle": "default"},
            {"source": "buttons", "target": "sales", "sourceHandle": "vendas"},
        ],
    }

    first = asyncio.run(execute_node_chain_until_reply(graph, "image", "", context={"channel": "simulator"}))

    assert first["next_node_id"] == "buttons"
    assert first["events"][:2] == [
        {"type": "send_image", "media_url": "https://cdn.ex/img.png", "caption": "Catálogo"},
        {"type": "send_document", "document_url": "https://cdn.ex/file.pdf", "filename": "file.pdf", "caption": "Contrato"},
    ]
    assert first["events"][2]["type"] == "send_buttons"
    assert len(first["events"][2]["buttons"]) == 2

    second = asyncio.run(execute_node_chain_until_reply(graph, "buttons", "Vendas", context={"channel": "simulator"}))

    assert second["events"][0]["event_type"] == "BUTTON_CLICKED"
    assert second["events"][1] == {"type": "send_message", "text": "Time comercial"}


def test_list_selection_runtime_and_analytics_event_type():
    graph = {
        "nodes": [
            {"id": "list", "type": "list_node", "data": {"isStart": True, "body_text": "Escolha uma área", "sections": [{"title": "Áreas", "rows": [{"title": "Financeiro", "handleId": "financeiro"}]}]}},
            {"id": "finance", "type": "message", "data": {"content": "Indo para financeiro"}},
        ],
        "edges": [{"source": "list", "target": "finance", "sourceHandle": "financeiro"}],
    }

    first = asyncio.run(execute_node_chain_until_reply(graph, "list", "", context={"channel": "simulator"}))
    assert first["events"][0]["type"] == "send_list"

    selected = asyncio.run(execute_node_chain_until_reply(graph, "list", "Financeiro", context={"channel": "simulator"}))
    assert selected["events"][0]["event_type"] == "LIST_SELECTED"
    assert selected["events"][1]["text"] == "Indo para financeiro"
    assert EVENT_TYPE_ALIASES["button_clicked"] == BUTTON_CLICKED
    assert EVENT_TYPE_ALIASES["list_selected"] == LIST_SELECTED


def test_whatsapp_cloud_payloads_for_image_document_buttons_and_list(monkeypatch):
    sent = []

    class Response:
        status_code = 200
        text = "{}"
        def raise_for_status(self):
            return None
        def json(self):
            return {"ok": True}

    def fake_post(url, headers, json, timeout):
        sent.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(whatsapp_service.requests, "post", fake_post)

    whatsapp_service.send_whatsapp_image(phone="+55 11 99999-0000", media_url="https://cdn.ex/img.png", caption="Foto", token="token", phone_number_id="123")
    whatsapp_service.send_whatsapp_document(phone="5511999990000", document_url="https://cdn.ex/file.pdf", filename="file.pdf", caption="PDF", token="token", phone_number_id="123")
    whatsapp_service.send_whatsapp_interactive_buttons(phone="5511999990000", body_text="Escolha", buttons=[{"label": "Vendas"}], token="token", phone_number_id="123")
    whatsapp_service.send_whatsapp_interactive_list(phone="5511999990000", body_text="Lista", sections=[{"title": "Áreas", "rows": [{"id": "fin", "title": "Financeiro"}]}], token="token", phone_number_id="123")

    assert sent[0]["json"]["type"] == "image"
    assert sent[1]["json"]["document"]["filename"] == "file.pdf"
    assert sent[2]["json"]["interactive"]["type"] == "button"
    assert sent[3]["json"]["interactive"]["type"] == "list"


def test_choice_node_generates_interactive_list_and_follows_selected_edge():
    graph = {
        "nodes": [
            {"id": "start", "type": "message", "data": {"content": "Olá"}},
            {"id": "choice", "type": "choice", "data": {"content": "Escolha uma área", "buttons": [{"label": "Vendas", "handleId": "vendas"}, {"label": "Suporte", "handleId": "suporte"}]}},
            {"id": "sales", "type": "message", "data": {"content": "Time comercial"}},
            {"id": "support", "type": "message", "data": {"content": "Time de suporte"}},
        ],
        "edges": [
            {"source": "start", "target": "choice", "sourceHandle": "default"},
            {"source": "choice", "target": "sales", "sourceHandle": "vendas"},
            {"source": "choice", "target": "support", "sourceHandle": "suporte"},
        ],
    }

    first = asyncio.run(execute_node_chain_until_reply(graph, "start", "", context={"channel": "simulator"}))

    assert first["events"][0] == {"type": "send_message", "text": "Olá"}
    assert first["events"][1]["type"] == "send_list"
    assert first["events"][1]["interactive_type"] == "list"
    assert first["events"][1]["options"] == [
        {"id": "vendas", "label": "Vendas", "handleId": "vendas"},
        {"id": "suporte", "label": "Suporte", "handleId": "suporte"},
    ]
    assert first["events"][1]["sections"] == [{"title": "Opções", "rows": [{"id": "vendas", "title": "Vendas"}, {"id": "suporte", "title": "Suporte"}]}]
    assert first["next_node_id"] == "choice"

    selected = asyncio.run(execute_node_chain_until_reply(graph, "choice", "suporte", context={"channel": "simulator"}))

    assert selected["events"][0] == {"type": "analytics", "event_type": "LIST_SELECTED", "node_id": "choice", "option_id": "suporte"}
    assert selected["events"][1] == {"type": "send_message", "text": "Time de suporte"}


def test_queue_transports_choice_interactive_list(monkeypatch):
    from app.services import queue as queue_service

    enqueued = []

    class Queue:
        def enqueue(self, func, **kwargs):
            enqueued.append({"func": func, **kwargs})
            return type("Job", (), {"id": "job-choice-list"})()

    monkeypatch.setattr(queue_service, "get_queue", lambda _name: Queue())
    monkeypatch.setattr(queue_service, "_runtime_commit", lambda: "test")

    job_id = queue_service.enqueue_send_message({
        "tenant_id": "tenant-1",
        "phone": "5511999990000",
        "text": "Escolha uma área",
        "interactive_type": "list",
        "sections": [{"title": "Opções", "rows": [{"id": "vendas", "title": "Vendas"}]}],
        "options": [{"id": "vendas", "label": "Vendas", "handleId": "vendas"}],
        "flow_id": "flow-1",
        "session_id": "session-1",
        "node_id": "choice-1",
        "node_type": "choice",
    })

    payload = enqueued[0]["message_data"]
    assert job_id == "job-choice-list"
    assert payload["interactive_type"] == "list"
    assert payload["sections"][0]["rows"][0]["id"] == "vendas"
    assert payload["options"][0]["handleId"] == "vendas"


def test_meta_message_service_sends_interactive_list(monkeypatch):
    from app.services import whatsapp_message_service

    posted = []

    class Client:
        def __init__(self, token):
            self.token = token

        async def post(self, endpoint, payload, context):
            posted.append({"endpoint": endpoint, "payload": payload, "context": context, "token": self.token})
            return {"messages": [{"id": "wamid.list"}]}

    monkeypatch.setattr(whatsapp_message_service, "MetaCloudClient", Client)

    response = whatsapp_message_service.send_interactive_list_via_meta(
        token="token",
        phone_number_id="123",
        to="+55 11 99999-0000",
        body_text="Escolha",
        sections=[{"title": "Opções", "rows": [{"id": "suporte", "title": "Suporte"}]}],
        context={"flow_id": "flow-1", "node_id": "choice-1"},
    )

    assert response["messages"][0]["id"] == "wamid.list"
    assert posted[0]["payload"]["type"] == "interactive"
    assert posted[0]["payload"]["interactive"]["type"] == "list"
    assert posted[0]["payload"]["interactive"]["action"]["sections"][0]["rows"][0]["id"] == "suporte"
