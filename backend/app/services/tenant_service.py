from datetime import datetime

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import AIConfig, Tenant


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
    tenant = db.execute(select(Tenant).where(Tenant.slug == "default")).scalar_one_or_none()
    if tenant:
        return tenant

    tenant = Tenant(
        name="Tenant Default",
        slug="default",
        phone_number_id="default-phone-id",
        plan="starter",
        max_monthly_messages=1000,
        admin_password="admin123",
    )
    db.add(tenant)
    db.flush()
    db.add(AIConfig(tenant_id=tenant.id))
    db.commit()
    db.refresh(tenant)
    return tenant


def resolve_tenant_by_phone_number_id(db: Session, phone_number_id: str | None) -> Tenant | None:
    if not phone_number_id:
        return None
    return db.execute(select(Tenant).where(Tenant.phone_number_id == phone_number_id)).scalar_one_or_none()


def get_current_tenant(
    x_tenant_slug: str = Header(default="", alias="X-Tenant-Slug"),
    x_tenant_password: str = Header(default="", alias="X-Tenant-Password"),
    tenant_slug: str = Query(default=""),
    tenant_password: str = Query(default=""),
    db: Session = Depends(get_db),
) -> Tenant:
    slug = (x_tenant_slug or tenant_slug).strip()
    password = (x_tenant_password or tenant_password).strip()
    if not slug or not password:
        raise HTTPException(status_code=401, detail="Tenant não autenticado")

    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if not tenant or tenant.admin_password != password:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    return tenant


def login_tenant(db: Session, slug: str, password: str) -> Tenant | None:
    tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if tenant and tenant.admin_password == password:
        return tenant
    return None
