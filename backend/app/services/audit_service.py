from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import TenantUser
from app.security.turnstile import get_client_ip


def to_json_safe(value: Any) -> Any:
    """Convert known domain values to JSON-compatible values for audit metadata.

    Unsupported values deliberately raise ``TypeError`` instead of being silently
    stringified, so unexpected objects cannot be hidden in the audit trail.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return to_json_safe(value.value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return to_json_safe(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    raise TypeError(f"Unsupported audit metadata type: {type(value).__name__}")


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    return to_json_safe(metadata) if metadata is not None else None


def write_audit_log(
    db: Session,
    *,
    action: str,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | UUID | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AuditLog:
    ip_address = get_client_ip(request) if request is not None else None
    user_agent = request.headers.get("user-agent") if request is not None else None
    row = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        metadata_json=_safe_metadata(metadata),
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    print(
        "[AUDIT]",
        f"action={action}",
        f"tenant_id={tenant_id}",
        f"user_id={user_id}",
        f"entity_type={entity_type}",
        f"entity_id={entity_id}",
    )
    if commit:
        db.commit()
    return row


def serialize_audit_log(row: AuditLog) -> dict[str, Any]:
    user = row.user if isinstance(row.user, TenantUser) else None
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "user_id": str(row.user_id) if row.user_id else None,
        "user_name": user.full_name if user else None,
        "user_email": user.email if user else None,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "metadata_json": row.metadata_json or {},
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
