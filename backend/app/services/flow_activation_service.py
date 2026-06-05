from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.models.flow import Flow

logger = logging.getLogger(__name__)

MULTIPLE_ACTIVE_FLOWS_LOG = "[MULTIPLE_ACTIVE_FLOWS]"


def _supports_postgres_advisory_lock(db: Session) -> bool:
    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    return dialect_name == "postgresql"


def _tenant_advisory_lock_key(tenant_id: uuid.UUID) -> int:
    # pg_advisory_xact_lock accepts a signed int64. Keep the value stable and positive.
    return int.from_bytes(tenant_id.bytes[:8], byteorder="big", signed=False) & 0x7FFFFFFFFFFFFFFF


def acquire_tenant_flow_activation_lock(db: Session, tenant_id: uuid.UUID) -> None:
    """Serialize publish/activation work for a tenant within the current transaction."""

    if _supports_postgres_advisory_lock(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _tenant_advisory_lock_key(tenant_id)})

    # Lock existing tenant flow rows too. This is a no-op on SQLite and useful on PostgreSQL
    # for writers that do not use the advisory lock yet.
    db.execute(select(Flow.id).where(Flow.tenant_id == tenant_id).with_for_update()).all()


def find_active_flows(db: Session, tenant_id: uuid.UUID) -> list[Flow]:
    return list(
        db.execute(
            select(Flow)
            .where(
                Flow.tenant_id == tenant_id,
                Flow.is_active.is_(True),
                Flow.is_deleted.is_(False),
                Flow.deleted_at.is_(None),
            )
            .order_by(Flow.updated_at.desc().nullslast(), Flow.created_at.desc().nullslast(), Flow.id.asc())
        )
        .scalars()
        .all()
    )


def log_multiple_active_flows(db: Session, tenant_id: uuid.UUID) -> list[Flow]:
    active_flows = find_active_flows(db=db, tenant_id=tenant_id)
    if len(active_flows) > 1:
        logger.error(
            "%s tenant_id=%s active_count=%s flow_ids=%s",
            MULTIPLE_ACTIVE_FLOWS_LOG,
            tenant_id,
            len(active_flows),
            [str(flow.id) for flow in active_flows],
        )
    return active_flows


def activate_flow_exclusively(
    *,
    db: Session,
    tenant_id: uuid.UUID,
    flow: Flow,
    ensure_published: Callable[[Session, Flow], None] | None = None,
) -> Flow:
    """Atomically make exactly one non-deleted flow active for a tenant.

    The caller owns commit/rollback. This function holds tenant-scoped locks, optionally
    publishes the selected flow while holding the lock, deactivates every sibling flow,
    then activates only the selected flow. The partial unique index added by migration is
    the final database backstop for concurrent writers.
    """

    acquire_tenant_flow_activation_lock(db=db, tenant_id=tenant_id)
    log_multiple_active_flows(db=db, tenant_id=tenant_id)

    locked_flow = db.execute(
        select(Flow)
        .where(
            Flow.id == flow.id,
            Flow.tenant_id == tenant_id,
            Flow.is_deleted.is_(False),
            Flow.deleted_at.is_(None),
        )
        .with_for_update()
    ).scalars().first()
    if locked_flow is not None:
        flow = locked_flow

    if ensure_published is not None:
        ensure_published(db, flow)

    db.execute(
        update(Flow)
        .where(
            Flow.tenant_id == tenant_id,
            Flow.id != flow.id,
            Flow.is_active.is_(True),
        )
        .values(is_active=False)
    )
    flow.is_active = True
    db.add(flow)
    db.flush()

    active_count = db.execute(
        select(func.count(Flow.id)).where(
            Flow.tenant_id == tenant_id,
            Flow.is_active.is_(True),
            Flow.is_deleted.is_(False),
            Flow.deleted_at.is_(None),
        )
    ).scalar_one()
    if active_count != 1:
        logger.error("%s tenant_id=%s active_count=%s selected_flow_id=%s", MULTIPLE_ACTIVE_FLOWS_LOG, tenant_id, active_count, flow.id)
        raise RuntimeError("tenant must have exactly one active flow after activation")
    return flow


def deactivate_tenant_flows_exclusively(*, db: Session, tenant_id: uuid.UUID) -> list[Flow]:
    acquire_tenant_flow_activation_lock(db=db, tenant_id=tenant_id)
    active_flows = log_multiple_active_flows(db=db, tenant_id=tenant_id)
    db.execute(update(Flow).where(Flow.tenant_id == tenant_id, Flow.is_active.is_(True)).values(is_active=False))
    db.flush()
    return active_flows
