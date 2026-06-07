from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Flow, Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.flow_runtime_selector import resolve_flow_runtime
from app.services.tenant_service import resolve_tenant_by_phone_number_id


@dataclass(frozen=True)
class RuntimeFlowDiagnostic:
    builder_tenant: str | None
    webhook_tenant: str | None
    phone_number_id: str | None
    active_flow_id: str | None
    published_version_id: str | None
    runtime: str | None
    match: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "builder_tenant": self.builder_tenant,
            "webhook_tenant": self.webhook_tenant,
            "phone_number_id": self.phone_number_id,
            "active_flow_id": self.active_flow_id,
            "published_version_id": self.published_version_id,
            "runtime": self.runtime,
            "match": self.match,
        }


def _normalize_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    text = str(value).strip()
    if not text:
        return None
    return uuid.UUID(text)


def get_builder_whatsapp_phone_number_id(db: Session, builder_tenant_id: uuid.UUID) -> str | None:
    provider = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == builder_tenant_id,
                TenantWhatsAppProvider.provider_type == "meta_cloud",
                TenantWhatsAppProvider.phone_number_id.is_not(None),
            )
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
                TenantWhatsAppProvider.created_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    if provider and str(provider.phone_number_id or "").strip():
        return str(provider.phone_number_id).strip()

    tenant = db.execute(select(Tenant).where(Tenant.id == builder_tenant_id)).scalars().first()
    legacy_phone_number_id = str(getattr(tenant, "phone_number_id", "") or "").strip() if tenant else ""
    return legacy_phone_number_id or None


def get_active_runtime_flow_for_tenant(db: Session, tenant_id: uuid.UUID | None) -> Flow | None:
    if tenant_id is None:
        return None
    return (
        db.execute(
            select(Flow)
            .where(
                Flow.tenant_id == tenant_id,
                Flow.is_active.is_(True),
                Flow.is_deleted.is_(False),
                Flow.deleted_at.is_(None),
                Flow.published_version_id.is_not(None),
            )
            .order_by(Flow.priority.desc(), Flow.created_at.asc(), Flow.id.asc())
        )
        .scalars()
        .first()
    )


def build_runtime_flow_diagnostic(
    db: Session,
    *,
    builder_tenant_id: uuid.UUID | str | None,
    phone_number_id: str | None = None,
) -> RuntimeFlowDiagnostic:
    builder_uuid = _normalize_uuid(builder_tenant_id)
    normalized_phone_number_id = str(phone_number_id or "").strip() or None
    if normalized_phone_number_id is None and builder_uuid is not None:
        normalized_phone_number_id = get_builder_whatsapp_phone_number_id(db, builder_uuid)

    webhook_tenant = resolve_tenant_by_phone_number_id(db, normalized_phone_number_id) if normalized_phone_number_id else None
    webhook_tenant_id = getattr(webhook_tenant, "id", None)
    active_flow = get_active_runtime_flow_for_tenant(db, webhook_tenant_id)

    return RuntimeFlowDiagnostic(
        builder_tenant=str(builder_uuid) if builder_uuid else None,
        webhook_tenant=str(webhook_tenant_id) if webhook_tenant_id else None,
        phone_number_id=normalized_phone_number_id,
        active_flow_id=str(active_flow.id) if active_flow else None,
        published_version_id=str(active_flow.published_version_id) if active_flow and active_flow.published_version_id else None,
        runtime=resolve_flow_runtime(active_flow) if active_flow else None,
        match=bool(builder_uuid and webhook_tenant_id and builder_uuid == webhook_tenant_id),
    )


def assert_flow_matches_whatsapp_tenant(db: Session, *, flow: Flow) -> None:
    """Block Builder activation when WhatsApp webhook would resolve another tenant."""

    flow_tenant_id = getattr(flow, "tenant_id", None)
    if not flow_tenant_id:
        return
    phone_number_id = get_builder_whatsapp_phone_number_id(db, flow_tenant_id)
    if not phone_number_id:
        return
    webhook_tenant = resolve_tenant_by_phone_number_id(db, phone_number_id)
    webhook_tenant_id = getattr(webhook_tenant, "id", None)
    if webhook_tenant_id and webhook_tenant_id != flow_tenant_id:
        raise ValueError(
            f"Este fluxo pertence ao tenant {flow_tenant_id}, mas o número WhatsApp está vinculado ao tenant {webhook_tenant_id}."
        )
