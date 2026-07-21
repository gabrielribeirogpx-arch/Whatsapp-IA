from datetime import datetime
import os
import logging
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIConfig, Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.cache_service import TTL_TENANT_SECONDS, cache_aside_json

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantResolution:
    tenant: Tenant
    source: str


class TenantLimitError(RuntimeError):
    """Erro de limite/plano para operações do tenant."""


def _current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def ensure_usage_window(tenant: Tenant) -> None:
    month = _current_month()
    if tenant.usage_month != month:
        tenant.usage_month = month
        tenant.messages_used_month = 0


def assert_tenant_can_send(tenant: Tenant) -> None:
    ensure_usage_window(tenant)
    if tenant.is_blocked:
        raise TenantLimitError("Tenant bloqueado pelo plano")
    if tenant.messages_used_month >= tenant.max_monthly_messages:
        raise TenantLimitError("Limite mensal de mensagens atingido")


def consume_usage(tenant: Tenant, amount: int = 1) -> None:
    ensure_usage_window(tenant)
    tenant.messages_used_month += amount


def get_or_create_default_tenant(db: Session) -> Tenant:
    tenant = db.execute(select(Tenant).where(Tenant.slug == "default")).scalars().first()
    if tenant:
        return tenant

    tenant = Tenant(
        name="Tenant Default",
        slug="default",
        phone_number_id=os.getenv("PHONE_NUMBER_ID", ""),
        plan="starter",
        max_monthly_messages=1000,
        admin_password="admin123",
    )
    db.add(tenant)
    db.flush()
    system_prompt = "Você é um assistente de vendas altamente persuasivo. Seu objetivo é responder clientes de forma natural e converter em venda."
    db.add(AIConfig(tenant_id=tenant.id, system_prompt=system_prompt))
    db.commit()
    db.refresh(tenant)
    return tenant


def get_tenant_by_phone_number_id(db: Session, phone_id: str | None) -> Tenant | None:
    if not phone_id:
        return None
    normalized = str(phone_id).strip()
    if not normalized:
        return None

    provider = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(TenantWhatsAppProvider.phone_number_id == normalized)
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
                TenantWhatsAppProvider.created_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    if provider:
        tenant = db.execute(select(Tenant).where(Tenant.id == provider.tenant_id)).scalars().first()
        logger.info(
            "[TENANT PHONE RESOLUTION] source=tenant_whatsapp_providers phone_number_id=%s tenant_id=%s provider_id=%s status=%s is_active=%s",
            normalized,
            provider.tenant_id,
            provider.id,
            provider.status,
            provider.is_active,
        )
        return tenant

    tenant = db.execute(select(Tenant).where(Tenant.phone_number_id == normalized)).scalars().first()
    logger.info(
        "[TENANT PHONE RESOLUTION] source=tenants_legacy phone_number_id=%s tenant_id=%s",
        normalized,
        tenant.id if tenant else None,
    )
    return tenant


def get_tenant_cached(db: Session, tenant_id: uuid.UUID) -> Tenant | None:
    key = f"tenant:{tenant_id}"

    def _loader():
        tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalars().first()
        if not tenant:
            return None
        return {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name, "phone_number_id": tenant.phone_number_id}

    payload = cache_aside_json(key, TTL_TENANT_SECONDS, _loader)
    if not payload:
        return None
    return db.execute(select(Tenant).where(Tenant.id == uuid.UUID(str(payload["id"])))).scalars().first()


def resolve_tenant_by_phone_number_id(db: Session, phone_number_id: str | None) -> Tenant | None:
    return get_tenant_by_phone_number_id(db, phone_number_id)


def resolve_current_tenant(
    request: Request,
    *,
    db: Session,
    x_tenant_slug: str = "",
    x_tenant_id: str = "",
    x_tenant_id_alt: str = "",
    tenant_slug: str = "",
    tenant_id: str = "",
) -> TenantResolution | None:
    candidates = [
        ("query id", tenant_id),
        ("header X-Tenant-Id", x_tenant_id),
        ("header X-Tenant-ID", x_tenant_id_alt),
    ]
    raw_tenant_id = ""
    id_source = ""
    for source, value in candidates:
        normalized = (value or "").strip()
        if normalized:
            raw_tenant_id = normalized
            id_source = source
            break

    slug_candidates = [("query slug", tenant_slug), ("header X-Tenant-Slug", x_tenant_slug)]
    slug = ""
    slug_source = ""
    for source, value in slug_candidates:
        normalized = (value or "").strip()
        if normalized:
            slug = normalized
            slug_source = source
            break

    middleware_tenant_id = getattr(request.state, "tenant_id", None)

    if raw_tenant_id and middleware_tenant_id and str(middleware_tenant_id) != str(raw_tenant_id):
        raise HTTPException(status_code=401, detail="Tenant ID do header não confere com o contexto da requisição")

    if raw_tenant_id:
        try:
            parsed_tenant_id = uuid.UUID(raw_tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Tenant ID inválido") from exc

        tenant = get_tenant_cached(db, parsed_tenant_id)
        if not tenant:
            return None
        return TenantResolution(tenant=tenant, source=id_source)

    if not slug:
        return None

    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first()
    if not tenant:
        return None

    return TenantResolution(tenant=tenant, source=slug_source)


def get_current_tenant_resolution(
    request: Request,
    x_tenant_slug: str = Header(default="", alias="X-Tenant-Slug"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    x_tenant_id_alt: str = Header(default="", alias="X-Tenant-ID"),
    tenant_slug: str = Query(default=""),
    tenant_id_query: str = Query(default="", alias="tenant_id"),
    db: Session = Depends(get_db),
) -> TenantResolution | None:
    return resolve_current_tenant(
        request,
        db=db,
        x_tenant_slug=x_tenant_slug,
        x_tenant_id=x_tenant_id,
        x_tenant_id_alt=x_tenant_id_alt,
        tenant_slug=tenant_slug,
        tenant_id=tenant_id_query,
    )


def get_current_tenant(
    request: Request,
    x_tenant_slug: str = Header(default="", alias="X-Tenant-Slug"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    x_tenant_id_alt: str = Header(default="", alias="X-Tenant-ID"),
    tenant_slug: str = Query(default=""),
    tenant_id_query: str = Query(default="", alias="tenant_id"),
    db: Session = Depends(get_db),
) -> Tenant:
    resolution = resolve_current_tenant(
        request,
        db=db,
        x_tenant_slug=x_tenant_slug,
        x_tenant_id=x_tenant_id,
        x_tenant_id_alt=x_tenant_id_alt,
        tenant_slug=tenant_slug,
        tenant_id=tenant_id_query,
    )
    if not resolution:
        if (tenant_id_query or x_tenant_id or x_tenant_id_alt or tenant_slug or x_tenant_slug):
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        raise HTTPException(status_code=401, detail="Tenant não autenticado")

    return resolution.tenant


def login_tenant(db: Session, slug: str) -> Tenant | None:
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first()
    if tenant:
        return tenant
    return None
