from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import REQUIRED_CORS_ORIGINS, preflight_handler
from app.models.lead import LeadStage, LeadStatus, LeadTemperature
from app.routers import leads as leads_router
from app.schemas.lead import LeadMoveRequest
from app.services.tenant_service import get_current_tenant


class _ScalarResult:
    def __init__(self, item):
        self.item = item

    def first(self):
        return self.item


class _ExecuteResult:
    def __init__(self, item):
        self.item = item

    def scalars(self):
        return _ScalarResult(self.item)


class _FakeDb:
    def __init__(self, *items):
        self.items = list(items)
        self.added = []
        self.commits = 0
        self.refreshed = []

    def execute(self, _statement):
        if not self.items:
            raise AssertionError("Unexpected database query")
        return _ExecuteResult(self.items.pop(0))

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        self.refreshed.append(item)


def _tenant(tenant_id: uuid.UUID | None = None):
    return SimpleNamespace(id=tenant_id or uuid.uuid4(), workspace_profile="private_sales")


def _stage(*, tenant_id: uuid.UUID, stage_id: uuid.UUID | None = None, name: str = "Analisando", is_final_stage: bool = False):
    return SimpleNamespace(
        id=stage_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        position=1,
        is_final_stage=is_final_stage,
    )


def _lead(*, tenant_id: uuid.UUID, lead_id: uuid.UUID | None = None, stage_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=lead_id or uuid.uuid4(),
        tenant_id=tenant_id,
        phone="5511999999999",
        name="Lead Teste",
        stage=LeadStage.LEAD.value,
        stage_id=stage_id,
        temperature=LeadTemperature.COLD.value,
        score=0,
        email=None,
        source="whatsapp",
        status=LeadStatus.ACTIVE.value,
        owner_id=None,
        contact_id=None,
        conversation_id=None,
        last_message=None,
        last_contact_at=datetime.utcnow(),
        last_interaction=None,
        entered_stage_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def test_move_lead_to_valid_stage_persists_stage_and_audit_log() -> None:
    tenant = _tenant()
    origin_stage_id = uuid.uuid4()
    target_stage = _stage(tenant_id=tenant.id)
    lead = _lead(tenant_id=tenant.id, stage_id=origin_stage_id)
    db = _FakeDb(lead, target_stage)

    response = leads_router.move_lead(
        lead.id,
        LeadMoveRequest(stage_id=target_stage.id),
        tenant=tenant,
        db=db,
    )

    assert response.status_code == 204
    assert response.body == b""
    assert lead.stage_id == target_stage.id
    assert lead.status == LeadStatus.ACTIVE.value
    assert lead.updated_at is not None
    assert lead.entered_stage_at is not None
    assert db.commits == 1
    assert db.refreshed == [lead]
    assert len(db.added) == 1
    audit_log = db.added[0]
    assert audit_log.action == "LEAD_MOVED"
    assert audit_log.tenant_id == tenant.id
    assert audit_log.metadata_json["from_stage_id"] == str(origin_stage_id)
    assert audit_log.metadata_json["to_stage_id"] == str(target_stage.id)


def test_move_lead_refuses_lead_from_another_tenant() -> None:
    tenant = _tenant()
    db = _FakeDb(None)

    with pytest.raises(leads_router.HTTPException) as exc:
        leads_router.move_lead(uuid.uuid4(), LeadMoveRequest(stage_id=uuid.uuid4()), tenant=tenant, db=db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Lead não encontrado"
    assert db.commits == 0


def test_move_lead_refuses_stage_from_another_tenant() -> None:
    tenant = _tenant()
    original_stage_id = uuid.uuid4()
    lead = _lead(tenant_id=tenant.id, stage_id=original_stage_id)
    db = _FakeDb(lead, None)

    with pytest.raises(leads_router.HTTPException) as exc:
        leads_router.move_lead(lead.id, LeadMoveRequest(stage_id=uuid.uuid4()), tenant=tenant, db=db)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Stage não encontrado"
    assert lead.stage_id == original_stage_id
    assert db.commits == 0

def test_move_lead_same_stage_is_idempotent_without_duplicate_audit() -> None:
    tenant = _tenant()
    stage_id = uuid.uuid4()
    target_stage = _stage(tenant_id=tenant.id, stage_id=stage_id)
    lead = _lead(tenant_id=tenant.id, stage_id=stage_id)
    db = _FakeDb(lead, target_stage)

    response = leads_router.move_lead(
        lead.id,
        LeadMoveRequest(stage_id=target_stage.id),
        tenant=tenant,
        db=db,
    )

    assert response.status_code == 204
    assert response.body == b""
    assert lead.stage_id == stage_id
    assert db.commits == 0
    assert db.refreshed == []
    assert db.added == []


def test_move_endpoint_empty_payload_returns_clear_422_without_500() -> None:
    tenant = _tenant()
    client = TestClient(_build_move_app(_FakeDb(), tenant))

    response = client.patch(f"/api/leads/{uuid.uuid4()}/move", json={})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "stage_id"


def test_move_endpoint_null_stage_id_returns_clear_422_without_500() -> None:
    tenant = _tenant()
    client = TestClient(_build_move_app(_FakeDb(), tenant))

    response = client.patch(f"/api/leads/{uuid.uuid4()}/move", json={"stage_id": None})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "stage_id"


def test_move_endpoint_validation_error_contains_cors_headers() -> None:
    tenant = _tenant()
    origin = "https://frontend-whatsapp-ia-production.up.railway.app"
    client = TestClient(_build_move_app(_FakeDb(), tenant))

    response = client.patch(
        f"/api/leads/{uuid.uuid4()}/move",
        json={},
        headers={"Origin": origin},
    )

    assert response.status_code == 422
    assert response.headers.get("access-control-allow-origin") == origin


def _build_move_app(db: _FakeDb | None = None, tenant=None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*REQUIRED_CORS_ORIGINS, "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.options("/{full_path:path}")(preflight_handler)
    app.include_router(leads_router.router, prefix="/api")

    if db is not None:
        def _override_get_db():
            yield db

        app.dependency_overrides[get_db] = _override_get_db
    if tenant is not None:
        app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app


def test_patch_move_endpoint_is_registered_with_api_prefix_and_matches_payload_schema() -> None:
    tenant = _tenant()
    target_stage = _stage(tenant_id=tenant.id)
    lead = _lead(tenant_id=tenant.id, stage_id=uuid.uuid4())
    client = TestClient(_build_move_app(_FakeDb(lead, target_stage), tenant))

    response = client.patch(f"/api/leads/{lead.id}/move", json={"stage_id": str(target_stage.id)})

    assert response.status_code == 204
    assert response.content == b""
    assert lead.stage_id == target_stage.id


def test_patch_move_endpoint_does_not_serialize_lead_after_commit() -> None:
    tenant = _tenant()
    target_stage = _stage(tenant_id=tenant.id)
    lead = _lead(tenant_id=tenant.id, stage_id=uuid.uuid4())
    lead.last_contact_at = None
    db = _FakeDb(lead, target_stage)
    client = TestClient(_build_move_app(db, tenant))

    response = client.patch(f"/api/leads/{lead.id}/move", json={"stage_id": str(target_stage.id)})

    assert response.status_code == 204
    assert response.content == b""
    assert db.commits == 1


def test_move_endpoint_invalid_payload_returns_clear_422_without_500() -> None:
    tenant = _tenant()
    client = TestClient(_build_move_app(_FakeDb(), tenant))

    response = client.patch(f"/api/leads/{uuid.uuid4()}/move", json={"pipeline_stage": str(uuid.uuid4())})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "stage_id"


def test_options_preflight_for_patch_move_contains_cors_headers() -> None:
    client = TestClient(_build_move_app())
    origin = "https://frontend-whatsapp-ia-production.up.railway.app"

    response = client.options(
        f"/api/leads/{uuid.uuid4()}/move",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Authorization, X-Tenant-ID, Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert "PATCH" in response.headers.get("access-control-allow-methods", "")
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "X-Tenant-ID" in allow_headers or "*" in allow_headers
