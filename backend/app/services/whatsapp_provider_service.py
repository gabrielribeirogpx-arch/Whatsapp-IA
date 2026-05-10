from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider


PROVIDER_REQUIRED_FIELDS = {
    "meta_cloud": ["waba_id", "phone_number_id", "business_id", "access_token_encrypted"],
    "bsp_360dialog": ["api_key_encrypted", "phone_number_id"],
}


def _mask_token(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value)-6)}{value[-3:]}"


def list_providers(db: Session, tenant_id: UUID):
    return db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().all()


def create_provider(db: Session, tenant_id: UUID, payload):
    data = payload.model_dump(exclude_unset=True)
    provider = TenantWhatsAppProvider(tenant_id=tenant_id, **_normalize_secret_fields(data))
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(db: Session, tenant_id: UUID, provider_id: UUID, payload):
    provider = _get_provider(db, tenant_id, provider_id)
    data = _normalize_secret_fields(payload.model_dump(exclude_unset=True))
    for key, value in data.items():
        setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return provider


def set_active_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.execute(update(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id).values(is_active=False))
    provider.is_active = True
    db.commit()
    db.refresh(provider)
    return provider


def delete_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.delete(provider)
    db.commit()


def get_active_provider(db: Session, tenant_id: UUID):
    return db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id, TenantWhatsAppProvider.is_active.is_(True))).scalars().first()


def test_provider_connection(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    required = PROVIDER_REQUIRED_FIELDS.get(provider.provider_type, ["phone_number_id"])
    missing = [field for field in required if not getattr(provider, field)]
    provider.last_connection_check_at = datetime.utcnow()
    if missing:
        provider.status = "invalid_config"
        message = f"Campos obrigatórios ausentes: {', '.join(missing)}"
        ok = False
    else:
        provider.status = "connected"
        message = "Conexão validada em modo seguro (simulado)."
        ok = True
    db.commit()
    return {"ok": ok, "status": provider.status, "message": message}


def _normalize_secret_fields(data: dict):
    mapped = dict(data)
    if "access_token" in mapped:
        mapped["access_token_encrypted"] = mapped.pop("access_token")
    if "app_secret" in mapped:
        mapped["app_secret_encrypted"] = mapped.pop("app_secret")
    if "api_key" in mapped:
        mapped["api_key_encrypted"] = mapped.pop("api_key")
    return mapped


def _get_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id, TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().first()
    if not provider:
        raise ValueError("Provider não encontrado")
    return provider
