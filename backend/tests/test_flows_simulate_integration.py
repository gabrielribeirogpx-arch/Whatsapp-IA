from __future__ import annotations

from fastapi import FastAPI
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


def test_post_simulate_returns_200_and_json(monkeypatch):
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **kwargs: _FakeFlow())
    monkeypatch.setattr(
        flows,
        "get_flow_graph",
        lambda flow_id, db: {
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
        "reply": "Olá",
        "current_node_id": "start",
        "selected_edge": None,
    }
