from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.db.base import Base
from app.models import AuditLog, Tenant, TenantUser
from app.routers import account


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture()
def rbac_client():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantUser.__table__, AuditLog.__table__])
    ids: dict[str, uuid.UUID] = {}
    with Session(engine) as db:
        tenant_a = Tenant(name="A", slug="a")
        tenant_b = Tenant(name="B", slug="b")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        ids.update(tenant_a=tenant_a.id, tenant_b=tenant_b.id)
        for role in ("owner", "admin", "member", "viewer"):
            row = TenantUser(tenant_id=tenant_a.id, full_name=role.title(), email=f"{role}@a.test", password_hash="x", role=role, status="active")
            db.add(row)
            db.flush()
            ids[role] = row.id
        other = TenantUser(tenant_id=tenant_b.id, full_name="Other", email="owner@b.test", password_hash="x", role="owner", status="active")
        db.add(other)
        db.flush()
        ids["other"] = other.id
        db.commit()

    api = FastAPI()
    api.include_router(account.router, prefix="/api")

    def override_db():
        with Session(engine) as db:
            yield db

    def current_tenant(x_tenant: str = Header(default="a")):
        with Session(engine) as db:
            return db.get(Tenant, ids["tenant_b"] if x_tenant == "b" else ids["tenant_a"])

    def current_user(x_actor: str = Header(default=""), tenant: Tenant = Depends(current_tenant)):
        if not x_actor:
            raise HTTPException(status_code=401, detail="Token obrigatório")
        with Session(engine) as db:
            user = db.get(TenantUser, ids[x_actor])
            if user.tenant_id != tenant.id:
                raise HTTPException(status_code=401, detail="Token não pertence ao tenant atual")
            db.expunge(user)
            return user

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[account.get_current_tenant] = current_tenant
    api.dependency_overrides[account.get_current_user] = current_user
    return TestClient(api), engine, ids


@pytest.mark.parametrize("role,expected", [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)])
def test_list_users_permission_matrix(rbac_client, role, expected):
    client, _, _ = rbac_client
    assert client.get("/api/workspace/users", headers={"x-actor": role}).status_code == expected


@pytest.mark.parametrize("role,expected", [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)])
def test_invite_permission_matrix(rbac_client, role, expected):
    client, _, _ = rbac_client
    response = client.post("/api/workspace/users", headers={"x-actor": role}, json={"name": "Invited User", "email": f"invite-{role}@test", "role": "viewer"})
    assert response.status_code == expected


@pytest.mark.parametrize("role,expected", [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)])
def test_update_member_permission_matrix(rbac_client, role, expected):
    client, _, ids = rbac_client
    response = client.patch(f"/api/workspace/users/{ids['member']}", headers={"x-actor": role}, json={"role": "viewer"})
    assert response.status_code == expected


@pytest.mark.parametrize("role,expected", [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)])
def test_deactivate_member_permission_matrix(rbac_client, role, expected):
    client, _, ids = rbac_client
    response = client.post(f"/api/workspace/users/{ids['member']}/deactivate", headers={"x-actor": role})
    assert response.status_code == expected


@pytest.mark.parametrize("path,method", [("/api/workspace/users", "get"), ("/api/workspace/users", "post"), ("/api/security/audit", "get")])
def test_administrative_endpoints_require_authentication(rbac_client, path, method):
    client, _, _ = rbac_client
    response = client.post(path, json={"name": "No Auth", "email": "noauth@test", "role": "member"}) if method == "post" else client.get(path)
    assert response.status_code == 401


def test_update_and_deactivate_require_authentication(rbac_client):
    client, _, ids = rbac_client
    assert client.patch(f"/api/workspace/users/{ids['member']}", json={"role": "viewer"}).status_code == 401
    assert client.post(f"/api/workspace/users/{ids['member']}/deactivate").status_code == 401


def test_owner_can_promote_another_user_and_audit_it(rbac_client):
    client, engine, ids = rbac_client
    response = client.patch(f"/api/workspace/users/{ids['member']}", headers={"x-actor": "owner"}, json={"role": "owner"})
    assert response.status_code == 200
    with Session(engine) as db:
        actions = {row.action for row in db.query(AuditLog).filter(AuditLog.entity_id == str(ids["member"])).all()}
        assert {"user_role_changed", "user_promoted"} <= actions


def test_admin_cannot_invite_owner_edit_owner_or_self_promote(rbac_client):
    client, _, ids = rbac_client
    assert client.post("/api/workspace/users", headers={"x-actor": "admin"}, json={"name": "Owner Two", "email": "owner2@test", "role": "owner"}).status_code == 403
    assert client.patch(f"/api/workspace/users/{ids['owner']}", headers={"x-actor": "admin"}, json={"name": "Changed"}).status_code == 403
    assert client.post(f"/api/workspace/users/{ids['owner']}/deactivate", headers={"x-actor": "admin"}).status_code == 403
    assert client.patch(f"/api/workspace/users/{ids['admin']}", headers={"x-actor": "admin"}, json={"role": "owner"}).status_code == 403


@pytest.mark.parametrize("operation", ["downgrade", "deactivate", "status"])
def test_last_owner_is_protected(rbac_client, operation):
    client, _, ids = rbac_client
    headers = {"x-actor": "other", "x-tenant": "b"}
    if operation == "downgrade":
        response = client.patch(f"/api/workspace/users/{ids['other']}", headers=headers, json={"role": "admin"})
    elif operation == "status":
        response = client.patch(f"/api/workspace/users/{ids['other']}", headers=headers, json={"status": "inactive"})
    else:
        response = client.post(f"/api/workspace/users/{ids['other']}/deactivate", headers=headers)
    # Self mutations are also forbidden; either invariant independently requires 403.
    assert response.status_code == 403


def test_cross_tenant_target_is_not_disclosed(rbac_client):
    client, _, ids = rbac_client
    response = client.patch(f"/api/workspace/users/{ids['other']}", headers={"x-actor": "owner"}, json={"role": "member"})
    assert response.status_code == 404


def test_unknown_roles_are_rejected_and_legacy_actor_fails_closed(rbac_client):
    client, engine, ids = rbac_client
    assert client.post("/api/workspace/users", headers={"x-actor": "owner"}, json={"name": "Analyst", "email": "analyst@test", "role": "analyst"}).status_code == 422
    with Session(engine) as db:
        db.get(TenantUser, ids["member"]).role = "analyst"
        db.commit()
    assert client.get("/api/workspace/users", headers={"x-actor": "member"}).status_code == 403
