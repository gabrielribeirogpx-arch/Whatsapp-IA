from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def require_tenant_id(tenant_id: uuid.UUID | None, *, context: str = "") -> uuid.UUID:
    if tenant_id is None:
        logger.error("[TENANT SECURITY] tenant_not_resolved context=%s", context or "n/a")
        raise ValueError("tenant_id is required")
    return tenant_id


def enforce_tenant_filter(query, model, tenant_id: uuid.UUID | None, *, context: str = ""):
    resolved_tenant_id = require_tenant_id(tenant_id, context=context)
    if not hasattr(model, "tenant_id"):
        logger.error("[TENANT SECURITY] query_without_tenant_column model=%s context=%s", getattr(model, "__name__", str(model)), context or "n/a")
        raise ValueError("model does not support tenant isolation")
    return query.where(model.tenant_id == resolved_tenant_id)
