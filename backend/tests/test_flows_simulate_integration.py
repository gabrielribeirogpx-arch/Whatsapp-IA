from __future__ import annotations

from fastapi import FastAPI
from unittest.mock import Mock
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import flows


class _DummyDb:
    pass


class _FakeFlow:
    id = "flow-1"


def _override_get_db():
    yield _DummyDb()


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(flows.crud_router, prefix="/api/flows")
    app.dependency_overrides[get_db] = _override_get_db
    return app


def test_post_simulate_contract_response_without_transition(monkeypatch):
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: _FakeFlow())
    monkeypatch.setattr(
        flows,
        "get_flow_graph",
        lambda **kwargs: {
            "nodes": [
                {
                    "id": "start",
                    "type": "message",
                    "data": {"isStart": True, "text": "Olá"},
                }
            ],
            "edges": [],
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        json={},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "reply": "Olá",
        "current_node_id": "start",
        "next_node_id": "start",
        "selected_edge": None,
    }


def test_post_simulate_does_not_send_whatsapp_and_returns_only_simulation_json(monkeypatch):
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: _FakeFlow())
    monkeypatch.setattr(
        flows,
        "get_flow_graph",
        lambda **kwargs: {
            "nodes": [
                {
                    "id": "start",
                    "type": "message",
                    "data": {"isStart": True, "text": "Simulação"},
                }
            ],
            "edges": [],
        },
    )

    blocked_send = Mock(side_effect=AssertionError("Função de envio WhatsApp não deve ser chamada em /simulate"))
    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_message", blocked_send)
    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_message_simple", blocked_send)
    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_message_cloud", blocked_send)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        json={"message": "oi"},
    )

    assert response.status_code == 200
    assert blocked_send.call_count == 0
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "reply": "Simulação",
        "current_node_id": "start",
        "next_node_id": "start",
        "selected_edge": None,
    }


def test_post_simulate_calls_get_flow_graph_with_required_flow_id(monkeypatch):
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: _FakeFlow())

    captured = {}

    def _fake_get_flow_graph(*, db, tenant_id, flow_id):
        captured["db"] = db
        captured["tenant_id"] = tenant_id
        captured["flow_id"] = flow_id
        return {
            "nodes": [
                {
                    "id": "start",
                    "type": "message",
                    "data": {"isStart": True, "text": "Olá"},
                }
            ],
            "edges": [],
        }

    monkeypatch.setattr(flows, "get_flow_graph", _fake_get_flow_graph)

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        json={"message": "oi"},
    )

    assert response.status_code == 200
    assert captured["flow_id"] == "flow-1"
    assert captured["tenant_id"] == "tenant-1"


def test_post_simulate_auto_continues_message_delay_message_until_condition(monkeypatch):
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: _FakeFlow())
    monkeypatch.setattr(
        flows,
        "get_flow_graph",
        lambda **kwargs: {
            "nodes": [
                {"id": "start", "type": "condition", "data": {"isStart": True, "condition": "sim"}},
                {"id": "d1", "type": "delay", "data": {"seconds": 2}},
                {"id": "m1", "type": "message", "data": {"text": "Message A"}},
                {"id": "d2", "type": "delay", "data": {"seconds": 2}},
                {"id": "m2", "type": "message", "data": {"text": "Message B"}},
                {"id": "c2", "type": "condition", "data": {"condition": "ok"}},
            ],
            "edges": [
                {"source": "start", "target": "d1", "sourceHandle": "true"},
                {"source": "d1", "target": "m1", "sourceHandle": "default"},
                {"source": "m1", "target": "d2", "sourceHandle": "default"},
                {"source": "d2", "target": "m2", "sourceHandle": "default"},
                {"source": "m2", "target": "c2", "sourceHandle": "default"},
            ],
        },
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        json={"session_id": "s1", "message": "sim"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["reply"] == "Message A\n\nMessage B"
    assert payload["next_node_id"] == "c2"
