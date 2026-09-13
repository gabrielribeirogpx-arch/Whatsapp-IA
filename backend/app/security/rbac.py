from __future__ import annotations

from enum import Enum

from fastapi import HTTPException


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class WorkspacePermission(str, Enum):
    LIST_USERS = "list_users"
    VIEW_AUDIT = "view_audit"
    INVITE_USERS = "invite_users"
    MANAGE_USERS = "manage_users"


PERMISSION_MATRIX: dict[WorkspaceRole, frozenset[WorkspacePermission]] = {
    WorkspaceRole.OWNER: frozenset(WorkspacePermission),
    WorkspaceRole.ADMIN: frozenset(
        {
            WorkspacePermission.LIST_USERS,
            WorkspacePermission.VIEW_AUDIT,
            WorkspacePermission.INVITE_USERS,
            WorkspacePermission.MANAGE_USERS,
        }
    ),
    WorkspaceRole.MEMBER: frozenset(),
    WorkspaceRole.VIEWER: frozenset(),
}

ROLE_RANK = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.OWNER: 3,
}


def canonical_role(value: object) -> WorkspaceRole | None:
    """Return a supported role, failing closed for legacy database values."""
    try:
        return WorkspaceRole(str(value))
    except ValueError:
        return None


def require_permission(actor: object, permission: WorkspacePermission) -> WorkspaceRole:
    role = canonical_role(getattr(actor, "role", None))
    if (
        role is None
        or getattr(actor, "status", None) != "active"
        or permission not in PERMISSION_MATRIX[role]
    ):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")
    return role


def require_invite_role(actor_role: WorkspaceRole, requested_role: WorkspaceRole) -> None:
    if actor_role == WorkspaceRole.ADMIN and requested_role not in {
        WorkspaceRole.MEMBER,
        WorkspaceRole.VIEWER,
    }:
        raise HTTPException(status_code=403, detail="Papel não autorizado para convite")


def require_target_management(
    actor: object,
    actor_role: WorkspaceRole,
    target: object,
    *,
    new_role: WorkspaceRole | None = None,
) -> None:
    target_role = canonical_role(getattr(target, "role", None))
    if getattr(actor, "id", None) == getattr(target, "id", None) and new_role is not None:
        raise HTTPException(status_code=403, detail="Não é permitido alterar o próprio papel")
    if new_role == WorkspaceRole.OWNER and actor_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="Somente owners podem promover outro owner")
    if actor_role == WorkspaceRole.ADMIN:
        if target_role not in {WorkspaceRole.MEMBER, WorkspaceRole.VIEWER}:
            raise HTTPException(status_code=403, detail="Admin não pode administrar este usuário")
        if new_role is not None and new_role not in {
            WorkspaceRole.MEMBER,
            WorkspaceRole.VIEWER,
        }:
            raise HTTPException(status_code=403, detail="Admin não pode atribuir este papel")


def role_change_action(old_role: WorkspaceRole | None, new_role: WorkspaceRole) -> str:
    if old_role is None or ROLE_RANK[new_role] == ROLE_RANK[old_role]:
        return "user_role_changed"
    return "user_promoted" if ROLE_RANK[new_role] > ROLE_RANK[old_role] else "user_demoted"
