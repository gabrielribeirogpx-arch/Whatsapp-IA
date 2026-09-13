from __future__ import annotations

import uuid
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.models.audit_log import AuditLog
from app.routers import account
from app.routers.account import get_current_user
from app.services.tenant_service import get_current_tenant


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


sqlite3.register_adapter(uuid.UUID, str)


@pytest.fixture()
def workspace(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Tenant.__table__.create(engine)
    TenantUser.__table__.create(engine)
    AuditLog.__table__.create(engine)
    db = Session(engine)
    tenant_a = Tenant(name="A", slug=f"a-{uuid.uuid4()}")
    tenant_b = Tenant(name="B", slug=f"b-{uuid.uuid4()}")
    db.add_all([tenant_a, tenant_b])
    db.flush()

    users = {}
    for role in ("owner", "admin", "member", "viewer"):
        row = TenantUser(
            tenant_id=tenant_a.id,
            full_name=role.title(),
            email=f"{role}-{uuid.uuid4()}@example.com",
            password_hash="unused",
            role=role,
            status="active",
        )
        db.add(row)
        users[role] = row
    outsider = TenantUser(
        tenant_id=tenant_b.id,
        full_name="Outsider",
        email=f"outside-{uuid.uuid4()}@example.com",
        password_hash="unused",
        role="owner",
        status="active",
    )
    db.add(outsider)
    db.commit()
    for row in [*users.values(), outsider, tenant_a, tenant_b]:
        db.refresh(row)

    audit_events = []

    def audit_stub(_db, **kwargs):
        audit_events.append(kwargs)

    monkeypatch.setattr(account, "write_audit_log", audit_stub)

    def client(actor=None, tenant=tenant_a):
        app = FastAPI()
        app.include_router(account.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_tenant] = lambda: tenant
        if actor is not None:
            app.dependency_overrides[get_current_user] = lambda: actor
        return TestClient(app)

    yield db, tenant_a, tenant_b, users, outsider, audit_events, client
    db.close()


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)],
)
def test_list_users_permission_matrix(workspace, role, status):
    *_, users, _outsider, _events, client = workspace
    assert client(users[role]).get("/workspace/users").status_code == status


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)],
)
def test_invite_permission_matrix_and_audit(workspace, role, status):
    *_, users, _outsider, events, client = workspace
    response = client(users[role]).post(
        "/workspace/users",
        json={"name": "New User", "email": f"new-{role}-{uuid.uuid4()}@example.com", "role": "member"},
    )
    assert response.status_code == status
    if status == 200:
        assert events[-1]["action"] == "user_invited"
        assert events[-1]["metadata"]["actor_user_id"] == str(users[role].id)


def test_owner_can_promote_another_user_to_owner_and_event_is_audited(workspace):
    *_, users, _outsider, events, client = workspace
    response = client(users["owner"]).patch(
        f"/workspace/users/{users['member'].id}", json={"role": "owner"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "owner"
    assert [event["action"] for event in events[-2:]] == ["user_role_changed", "user_promoted"]


def test_admin_can_only_manage_member_and_viewer(workspace):
    *_, users, _outsider, _events, client = workspace
    admin_client = client(users["admin"])
    assert admin_client.patch(
        f"/workspace/users/{users['member'].id}", json={"role": "viewer"}
    ).status_code == 200
    assert admin_client.patch(
        f"/workspace/users/{users['viewer'].id}", json={"role": "owner"}
    ).status_code == 403
    assert admin_client.patch(
        f"/workspace/users/{users['owner'].id}", json={"name": "Changed"}
    ).status_code == 403
    assert admin_client.post(
        f"/workspace/users/{users['owner'].id}/deactivate"
    ).status_code == 403


def test_admin_cannot_elevate_itself_or_invite_owner(workspace):
    *_, users, _outsider, _events, client = workspace
    admin_client = client(users["admin"])
    assert admin_client.patch(
        f"/workspace/users/{users['admin'].id}", json={"role": "owner"}
    ).status_code == 403
    assert admin_client.post(
        "/workspace/users",
        json={"name": "Owner Two", "email": f"owner-{uuid.uuid4()}@example.com", "role": "owner"},
    ).status_code == 403


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_non_admin_cannot_patch_or_deactivate_directly(workspace, role):
    *_, users, _outsider, _events, client = workspace
    api = client(users[role])
    assert api.patch(
        f"/workspace/users/{users['viewer'].id}", json={"role": "owner"}
    ).status_code == 403
    assert api.post(
        f"/workspace/users/{users['viewer'].id}/deactivate"
    ).status_code == 403
    assert api.delete(f"/workspace/users/{users['viewer'].id}").status_code == 403


def test_last_owner_cannot_be_downgraded_or_deactivated(workspace):
    db, _tenant, _other, users, _outsider, _events, client = workspace
    db.delete(users["admin"])
    db.commit()
    owner_client = client(users["owner"])
    assert owner_client.patch(
        f"/workspace/users/{users['owner'].id}", json={"role": "admin"}
    ).status_code == 403
    # Self-deactivation is forbidden independently and also cannot remove the last owner.
    assert owner_client.post(
        f"/workspace/users/{users['owner'].id}/deactivate"
    ).status_code == 403
    assert owner_client.delete(f"/workspace/users/{users['owner'].id}").status_code == 403


def test_owner_and_admin_can_remove_permitted_users_with_audit(workspace):
    db, tenant, _other, users, _outsider, events, client = workspace
    removable = TenantUser(tenant_id=tenant.id, full_name="Remove Me", email=f"remove-{uuid.uuid4()}@x.test", password_hash="x", role="viewer", status="active")
    db.add(removable)
    db.commit()
    db.refresh(removable)
    assert client(users["admin"]).delete(f"/workspace/users/{removable.id}").status_code == 204
    assert events[-1]["action"] == "user_removed"

    removable = TenantUser(tenant_id=tenant.id, full_name="Remove Me Too", email=f"remove-{uuid.uuid4()}@x.test", password_hash="x", role="admin", status="active")
    db.add(removable)
    db.commit()
    db.refresh(removable)
    assert client(users["owner"]).delete(f"/workspace/users/{removable.id}").status_code == 204
    assert events[-1]["action"] == "user_removed"


def test_owner_cannot_deactivate_the_only_other_active_owner(workspace):
    db, tenant, _other, users, _outsider, _events, client = workspace
    users["member"].role = "owner"
    db.delete(users["owner"])
    db.commit()
    # Add a non-owner actor with owner authority only after target lookup is fixed:
    actor = TenantUser(tenant_id=tenant.id, full_name="Actor", email=f"actor-{uuid.uuid4()}@x.test", password_hash="x", role="owner", status="inactive")
    db.add(actor)
    db.commit()
    # An inactive actor cannot occur through real authentication; policy still protects count.
    assert client(actor).post(f"/workspace/users/{users['member'].id}/deactivate").status_code == 403


def test_cross_tenant_target_is_not_disclosed(workspace):
    *_, users, outsider, _events, client = workspace
    response = client(users["owner"]).patch(
        f"/workspace/users/{outsider.id}", json={"role": "viewer"}
    )
    assert response.status_code == 404
    assert client(users["owner"]).delete(f"/workspace/users/{outsider.id}").status_code == 404


def test_actor_tenant_mismatch_is_not_disclosed(workspace):
    _db, _a, tenant_b, users, _outsider, _events, client = workspace
    assert client(users["owner"], tenant_b).get("/workspace/users").status_code == 404
    assert client(users["owner"], tenant_b).post(
        "/workspace/users", json={"name": "No Leak", "email": f"no-leak-{uuid.uuid4()}@x.test", "role": "member"}
    ).status_code == 404
    assert client(users["owner"]).post(f"/workspace/users/{_outsider.id}/deactivate").status_code == 404


@pytest.mark.parametrize("role", ["superadmin", "analyst", "OWNER ", ""])
def test_backend_rejects_noncanonical_roles(workspace, role):
    *_, users, _outsider, _events, client = workspace
    response = client(users["owner"]).post(
        "/workspace/users",
        json={"name": "Bad Role", "email": f"bad-{uuid.uuid4()}@example.com", "role": role},
    )
    assert response.status_code == 422


def test_backend_rejects_arbitrary_status_and_audits_enable_disable(workspace):
    *_, users, _outsider, events, client = workspace
    owner_client = client(users["owner"])
    target = users["member"]
    assert owner_client.patch(
        f"/workspace/users/{target.id}", json={"status": "deleted"}
    ).status_code == 422
    assert owner_client.patch(
        f"/workspace/users/{target.id}", json={"status": "inactive"}
    ).status_code == 200
    assert events[-1]["action"] == "user_disabled"
    assert owner_client.patch(
        f"/workspace/users/{target.id}", json={"status": "active"}
    ).status_code == 200
    assert events[-1]["action"] == "user_enabled"


def test_unauthenticated_request_returns_401(workspace):
    *_, users, _outsider, _events, client = workspace
    api = client()
    requests = (
        api.get("/workspace/users"),
        api.post("/workspace/users", json={"name": "No Auth", "email": "no-auth@example.com", "role": "member"}),
        api.patch(f"/workspace/users/{users['member'].id}", json={"role": "viewer"}),
        api.post(f"/workspace/users/{users['member'].id}/deactivate"),
        api.delete(f"/workspace/users/{users['member'].id}"),
        api.get("/security/audit"),
    )
    assert [response.status_code for response in requests] == [401] * len(requests)


@pytest.mark.parametrize(
    ("role", "status"),
    [("owner", 200), ("admin", 200), ("member", 403), ("viewer", 403)],
)
def test_audit_log_permission_matrix(workspace, role, status):
    *_, users, _outsider, _events, client = workspace
    assert client(users[role]).get("/security/audit").status_code == status
