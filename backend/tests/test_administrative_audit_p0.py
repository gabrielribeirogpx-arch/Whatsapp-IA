from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.security.workspace_rbac import WorkspacePermission
from app.services import administrative_audit


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_admin_denial_persists_actor_and_tenant(monkeypatch):
    actor = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="member")
    db = FakeDb()
    captured = {}
    monkeypatch.setattr(administrative_audit, "write_audit_log", lambda _db, **kwargs: captured.update(kwargs))

    with pytest.raises(HTTPException) as denied:
        administrative_audit.require_administrative_permission(
            db, actor, WorkspacePermission.MANAGE_SETTINGS,
            request=None, action="tenant_settings_updated", resource_type="tenant_settings",
        )

    assert denied.value.status_code == 403
    assert captured["action"] == "admin_permission_denied"
    assert captured["tenant_id"] == actor.tenant_id
    assert captured["user_id"] == actor.id
    assert captured["metadata"]["reason_code"] == "insufficient_permission"


def test_admin_denial_survives_security_audit_failure(monkeypatch):
    actor = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="viewer")
    db = FakeDb()
    monkeypatch.setattr(administrative_audit, "write_audit_log", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")))

    with pytest.raises(HTTPException) as denied:
        administrative_audit.require_administrative_permission(
            db, actor, WorkspacePermission.MANAGE_INTEGRATIONS,
            request=None, action="integration_disconnected", resource_type="integration",
        )

    assert denied.value.status_code == 403
    assert db.rollbacks == 1


def test_owner_and_admin_have_new_administrative_permissions():
    for role in ("owner", "admin"):
        actor = SimpleNamespace(role=role)
        administrative_audit.require_permission(actor, WorkspacePermission.MANAGE_SETTINGS)
        administrative_audit.require_permission(actor, WorkspacePermission.MANAGE_INTEGRATIONS)
