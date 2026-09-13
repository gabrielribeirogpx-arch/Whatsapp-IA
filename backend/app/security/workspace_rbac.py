from __future__ import annotations

from enum import Enum

from fastapi import HTTPException

from app.models.user import TenantUser


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class WorkspaceUserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AdministrativeAuditAction(str, Enum):
    USER_INVITED = "user_invited"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_PROMOTED = "user_promoted"
    USER_DEMOTED = "user_demoted"
    USER_DISABLED = "user_disabled"
    USER_ENABLED = "user_enabled"
    USER_REMOVED = "user_removed"


class WorkspacePermission(str, Enum):
    LIST_USERS = "list_users"
    VIEW_USERS = "view_users"
    INVITE_USERS = "invite_users"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT_LOG = "view_audit_log"


ROLE_RANK: dict[WorkspaceRole, int] = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.OWNER: 3,
}

PERMISSION_MATRIX: dict[WorkspaceRole, frozenset[WorkspacePermission]] = {
    WorkspaceRole.OWNER: frozenset(WorkspacePermission),
    WorkspaceRole.ADMIN: frozenset(
        {
            WorkspacePermission.LIST_USERS,
            WorkspacePermission.VIEW_USERS,
            WorkspacePermission.INVITE_USERS,
            WorkspacePermission.MANAGE_USERS,
            WorkspacePermission.VIEW_AUDIT_LOG,
        }
    ),
    WorkspaceRole.MEMBER: frozenset(),
    WorkspaceRole.VIEWER: frozenset(),
}


def canonical_role(value: str | WorkspaceRole | None) -> WorkspaceRole | None:
    """Return a supported role; legacy/unknown database values fail closed."""
    try:
        return WorkspaceRole(str(value).lower())
    except (TypeError, ValueError):
        return None


def require_permission(actor: TenantUser, permission: WorkspacePermission) -> WorkspaceRole:
    role = canonical_role(actor.role)
    if role is None or permission not in PERMISSION_MATRIX[role]:
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    return role


def require_same_tenant(actor: TenantUser, tenant_id: object) -> None:
    if str(actor.tenant_id) != str(tenant_id):
        # Do not disclose whether a cross-tenant target exists.
        raise HTTPException(status_code=404, detail="Usuário não encontrado")


def authorize_invitation(actor: TenantUser, invited_role: WorkspaceRole) -> None:
    actor_role = require_permission(actor, WorkspacePermission.INVITE_USERS)
    if actor_role == WorkspaceRole.ADMIN and invited_role not in {
        WorkspaceRole.MEMBER,
        WorkspaceRole.VIEWER,
    }:
        raise HTTPException(status_code=403, detail="Administradores só podem convidar membros e visualizadores")


def authorize_user_change(
    actor: TenantUser,
    target: TenantUser,
    *,
    new_role: WorkspaceRole | None = None,
) -> None:
    actor_role = require_permission(actor, WorkspacePermission.MANAGE_USERS)
    require_same_tenant(actor, target.tenant_id)
    target_role = canonical_role(target.role)

    if actor_role == WorkspaceRole.ADMIN:
        if target_role not in {WorkspaceRole.MEMBER, WorkspaceRole.VIEWER}:
            raise HTTPException(status_code=403, detail="Administradores só podem gerenciar membros e visualizadores")
        if new_role is not None and new_role not in {WorkspaceRole.MEMBER, WorkspaceRole.VIEWER}:
            raise HTTPException(status_code=403, detail="Administradores só podem atribuir member ou viewer")

    if new_role == WorkspaceRole.OWNER and actor_role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="Somente owners podem promover outro owner")

    current_rank = ROLE_RANK.get(target_role) if target_role is not None else None
    if target.id == actor.id and new_role is not None:
        if current_rank is None or ROLE_RANK[new_role] > current_rank:
            raise HTTPException(status_code=403, detail="Autoelevação de privilégio não permitida")
