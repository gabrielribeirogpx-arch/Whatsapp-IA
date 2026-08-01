from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import FlowSession
from app.routers import flows


class _Query:
    def filter(self, *_args):
        return self

    def first(self):
        return None


class _Db:
    def __init__(self):
        self.added = []

    def query(self, *_args):
        return _Query()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        return None


def _app(db):
    app = FastAPI()
    app.include_router(flows.crud_router, prefix="/api/flows")
    app.dependency_overrides[get_db] = lambda: db
    return app


def _flow():
    return SimpleNamespace(id="flow-1", tenant_id="tenant-1", published_version_id="version-1")


def _version():
    node = {"id": "start", "type": "message", "data": {"isStart": True, "isFinal": True, "text": "Olá"}}
    return SimpleNamespace(id="version-1", snapshot={"nodes": [node], "edges": []}, nodes=None, edges=None)


def test_simulator_persists_the_resolved_published_version(monkeypatch):
    db = _Db()
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _value: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **_kwargs: _flow())
    monkeypatch.setattr(flows, "_get_published_version_for_simulation", lambda **_kwargs: _version())

    async def execute(**_kwargs):
        return {"reply": "Olá", "response_node_id": "start", "next_node_id": None, "events": []}

    monkeypatch.setattr(flows, "execute_node_chain_until_reply", execute)

    response = TestClient(_app(db)).post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "tenant-1"},
        json={"session_id": "published-version"},
    )

    assert response.status_code == 200
    session = next(value for value in db.added if isinstance(value, FlowSession))
    assert session.flow_version_id == "version-1"


def test_simulator_returns_domain_conflict_when_no_published_version_exists(monkeypatch):
    db = _Db()
    monkeypatch.setattr(flows, "_resolve_tenant_header", lambda _value: "tenant-1")
    monkeypatch.setattr(flows, "_get_flow_by_identifier", lambda **_kwargs: _flow())
    monkeypatch.setattr(flows, "_get_published_version_for_simulation", lambda **_kwargs: None)

    response = TestClient(_app(db)).post(
        "/api/flows/flow-1/simulate",
        headers={"X-Tenant-ID": "tenant-1"},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "FLOW_PUBLISHED_VERSION_NOT_FOUND"
    assert db.added == []
