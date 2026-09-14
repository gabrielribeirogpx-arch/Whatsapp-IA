"""Shared policy boundary for privileged administrative mutations."""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.user import TenantUser
from app.security.workspace_rbac import WorkspacePermission, require_permission
from app.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)


def require_administrative_permission(
    db: Session,
    actor: TenantUser,
    permission: WorkspacePermission,
    *,
    request: Request | None,
    action: str,
    resource_type: str,
    resource_id: object | None = None,
) -> None:
    """Fail closed and best-effort persist high-value administrative denials."""
    try:
        require_permission(actor, permission)
        return
    except HTTPException as denial:
        try:
            write_audit_log(
                db,
                action="admin_permission_denied",
                tenant_id=actor.tenant_id,
                user_id=actor.id,
                entity_type=resource_type,
                entity_id=resource_id,
                metadata={"attempted_action": action, "reason_code": "insufficient_permission"},
                request=request,
                commit=True,
            )
        except Exception:
            db.rollback()
            logger.warning(
                "event=security_audit_persist_failed tenant_id=%s action=%s reason_code=insufficient_permission",
                actor.tenant_id,
                action,
            )
        raise denial
