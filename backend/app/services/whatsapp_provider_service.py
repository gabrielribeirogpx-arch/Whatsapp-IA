from datetime import datetime
from uuid import UUID
import asyncio
import os

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.utils.encryption import decrypt_secret, encrypt_secret

PROVIDER_REQUIRED_FIELDS = {
    "meta_cloud": ["waba_id", "phone_number_id", "business_id", "access_token_encrypted"],
    "bsp_360dialog": ["api_key_encrypted", "phone_number_id"],
}


def list_providers(db: Session, tenant_id: UUID):
    return db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().all()


def create_provider(db: Session, tenant_id: UUID, payload):
    try:
        data = payload.model_dump(exclude_unset=True)
        provider = TenantWhatsAppProvider(tenant_id=tenant_id, **_normalize_secret_fields(data))
        db.add(provider)
        db.commit()
        db.refresh(provider)
        return provider
    except Exception:
        db.rollback()
        raise


def update_provider(db: Session, tenant_id: UUID, provider_id: UUID, payload):
    provider = _get_provider(db, tenant_id, provider_id)
    for key, value in _normalize_secret_fields(payload.model_dump(exclude_unset=True)).items():
        setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return provider


def set_active_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.execute(update(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id).values(is_active=False))
    provider.is_active = True
    provider.status = "active"
    db.commit()
    db.refresh(provider)
    return provider


def delete_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.delete(provider)
    db.commit()


def test_provider_connection(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    required = PROVIDER_REQUIRED_FIELDS.get(provider.provider_type, ["phone_number_id"])
    missing = [field for field in required if not getattr(provider, field)]
    provider.last_connection_check_at = datetime.utcnow()
    if missing:
        provider.status = "invalid_config"
        message = f"Campos obrigatórios ausentes: {', '.join(missing)}"
        db.commit()
        return {"ok": False, "status": provider.status, "message": message}

    if not os.getenv("WHATSAPP_SECRET_ENCRYPTION_KEY", "").strip():
        provider.status = "invalid_config"
        db.commit()
        return {"ok": False, "status": provider.status, "message": "WHATSAPP_SECRET_ENCRYPTION_KEY não configurada."}

    if provider.provider_type != "meta_cloud":
        provider.status = "connected"
        db.commit()
        return {"ok": True, "status": provider.status, "message": "Conexão validada para provider não-Meta."}

    token = decrypt_secret(provider.access_token_encrypted)
    if not token:
        provider.status = "invalid_config"
        db.commit()
        return {"ok": False, "status": provider.status, "message": "Token inválido ou ausente."}

    try:
        metadata = asyncio.run(_sync_meta_provider_metadata(provider, token, str(tenant_id)))
        provider.metadata_json = {**(provider.metadata_json or {}), **metadata}
        provider.status = "connected"
        provider.last_connection_check_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": provider.status, "message": "Conexão Meta validada com sucesso.", "metadata": metadata}
    except MetaApiError as exc:
        provider.status = "invalid_config"
        provider.metadata_json = {**(provider.metadata_json or {}), "last_error": str(exc)}
        db.commit()
        return {"ok": False, "status": provider.status, "message": str(exc)}


def _normalize_secret_fields(data: dict):
    mapped = dict(data)
    for source, target in (("access_token", "access_token_encrypted"), ("app_secret", "app_secret_encrypted"), ("api_key", "api_key_encrypted")):
        if source in mapped:
            mapped[target] = encrypt_secret(mapped.pop(source))
        elif target in mapped and mapped[target]:
            plain = decrypt_secret(mapped[target])
            mapped[target] = encrypt_secret(plain)
    return mapped


def _get_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id, TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().first()
    if not provider:
        raise ValueError("Provider não encontrado")
    return provider


async def _sync_meta_provider_metadata(provider: TenantWhatsAppProvider, token: str, tenant_id: str) -> dict:
    client = MetaCloudClient(token)
    context = {"tenant_id": tenant_id, "provider_id": str(provider.id)}
    phone = await client.get(f"/{provider.phone_number_id}", params={"fields": "verified_name,display_phone_number,quality_rating,status"}, context=context)
    waba = await client.get(f"/{provider.waba_id}", params={"fields": "name,message_template_namespace"}, context=context)
    business = await client.get(f"/{provider.business_id}", params={"fields": "name"}, context=context)
    return {
        "verified_name": phone.get("verified_name"),
        "display_phone_number": phone.get("display_phone_number"),
        "quality_rating": phone.get("quality_rating"),
        "phone_status": phone.get("status"),
        "messaging_limit_tier": phone.get("messaging_limit_tier") or phone.get("quality_rating"),
        "business_name": business.get("name"),
        "waba_name": waba.get("name"),
        "last_sync_at": datetime.utcnow().isoformat(),
    }
