from datetime import datetime
import os
import uuid

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_tenant_token
from app.database import get_db
from app.models import AIConfig, Tenant


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
    return db.execute(select(Tenant).where(Tenant.phone_number_id == phone_id)).scalars().first()


def resolve_tenant_by_phone_number_id(db: Session, phone_number_id: str | None) -> Tenant | None:
    return get_tenant_by_phone_number_id(db, phone_number_id)


def get_current_tenant(
    authorization: str = Header(default="", alias="Authorization"),
    x_tenant_slug: str = Header(default="", alias="X-Tenant-Slug"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    tenant_slug: str = Query(default=""),
    tenant_id: str = Query(default=""),
    db: Session = Depends(get_db),
) -> Tenant:
    raw_tenant_id = (x_tenant_id or tenant_id).strip()
    slug = (x_tenant_slug or tenant_slug).strip()

    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_tenant_token(token)
        raw_tenant_id = str(payload.get("tenant_id") or payload.get("sub") or "").strip() or raw_tenant_id
        slug = str(payload.get("slug") or "").strip() or slug

    if raw_tenant_id:
        try:
            parsed_tenant_id = uuid.UUID(raw_tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Tenant ID inválido") from exc

        tenant = db.execute(select(Tenant).where(Tenant.id == parsed_tenant_id)).scalars().first()
        if not tenant:
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        return tenant

    if not slug:
        raise HTTPException(status_code=401, detail="Tenant não autenticado")

    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    return tenant


def login_tenant(db: Session, slug: str) -> Tenant | None:
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalars().first()
    if tenant:
        return tenant
    return None
