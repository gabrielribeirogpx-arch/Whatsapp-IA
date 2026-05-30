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
