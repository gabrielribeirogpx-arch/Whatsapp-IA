from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers.flows import require_flow_view
from app.security.workspace_rbac import (
    WorkspacePermission,
    require_permission,
)


def _user(role: str):
    return SimpleNamespace(role=role)


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
def test_all_workspace_roles_can_view_flows(role):
    require_permission(_user(role), WorkspacePermission.VIEW_FLOWS)


@pytest.mark.parametrize("role", ["owner", "admin"])
@pytest.mark.parametrize(
    "permission",
    [
        WorkspacePermission.MANAGE_FLOWS,
        WorkspacePermission.PUBLISH_FLOWS,
        WorkspacePermission.ACTIVATE_FLOWS,
    ],
)
def test_owner_and_admin_can_administer_flows(role, permission):
    require_permission(_user(role), permission)


@pytest.mark.parametrize("role", ["member", "viewer"])
@pytest.mark.parametrize(
    "permission",
    [
        WorkspacePermission.MANAGE_FLOWS,
        WorkspacePermission.PUBLISH_FLOWS,
        WorkspacePermission.ACTIVATE_FLOWS,
        WorkspacePermission.MANAGE_SETTINGS,
    ],
)
def test_read_only_roles_cannot_mutate_flows_or_appointment_policy(role, permission):
    with pytest.raises(HTTPException) as exc:
        require_permission(_user(role), permission)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_can_manage_appointment_policy(role):
    require_permission(_user(role), WorkspacePermission.MANAGE_SETTINGS)


def test_unknown_and_inactive_style_roles_fail_closed():
    with pytest.raises(HTTPException) as exc:
        require_permission(_user("invited"), WorkspacePermission.VIEW_FLOWS)
    assert exc.value.status_code == 403


def test_legacy_tenant_path_cannot_cross_authenticated_tenant():
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/admin/tenant/tenant-b",
        "headers": [],
        "query_string": b"",
        "path_params": {"tenant_id": "tenant-b"},
        "server": ("testserver", 80),
        "scheme": "http",
    })
    actor = SimpleNamespace(id="user-a", tenant_id="tenant-a", role="owner")

    with pytest.raises(HTTPException) as exc:
        require_flow_view(request=request, db=SimpleNamespace(), current_user=actor)
    assert exc.value.status_code == 404
