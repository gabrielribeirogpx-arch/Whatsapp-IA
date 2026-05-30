from datetime import datetime
from uuid import UUID
import asyncio
import logging
import os

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.whatsapp_message_service import resolve_active_meta_provider_credentials
from app.utils.encryption import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

PROVIDER_REQUIRED_FIELDS = {
    "meta_cloud": ["waba_id", "phone_number_id", "business_id", "access_token_encrypted"],
    "bsp_360dialog": ["api_key_encrypted", "phone_number_id"],
}


def list_providers(db: Session, tenant_id: UUID):
    providers = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().all()
    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_count=%s active_count=%s providers=%s",
        tenant_id,
        "n/a",
        len(providers),
        sum(1 for provider in providers if provider.is_active),
        [
            {
                "provider_id": str(provider.id),
                "provider_name": provider.display_name,
                "is_active": provider.is_active,
                "status": provider.status,
                "phone_number_id": provider.phone_number_id,
                "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
            }
            for provider in providers
        ],
    )
    return providers


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
    incoming = payload.model_dump(exclude_unset=True)
    token_was_updated = "access_token" in incoming and str(incoming.get("access_token") or "").strip() != ""
    for secret_field in ("access_token", "app_secret", "api_key"):
        if secret_field in incoming and (incoming[secret_field] is None or str(incoming[secret_field]).strip() == ""):
            incoming.pop(secret_field, None)
    for key, value in _normalize_secret_fields(incoming).items():
        if value is None:
            continue
        setattr(provider, key, value)
    if token_was_updated and provider.is_active and provider.provider_type == "meta_cloud":
        provider.status = "active"
    provider.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(provider)
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s is_active=%s updated_at=%s token_updated=%s",
        provider.id,
        provider.is_active,
        provider.updated_at.isoformat() if provider.updated_at else None,
        token_was_updated,
    )
    return provider


def set_active_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.execute(update(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id).values(is_active=False))
    provider.is_active = True
    provider.status = "active"
    provider.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(provider)
    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_id=%s phone_number_id=%s action=activate",
        tenant_id,
        "n/a",
        provider.id,
        provider.phone_number_id,
    )
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s is_active=%s updated_at=%s",
        provider.id,
        provider.is_active,
        provider.updated_at.isoformat() if provider.updated_at else None,
    )
    return provider



def test_worker_active_provider_connection(db: Session, tenant_id: UUID):
    active_provider = resolve_active_meta_provider_credentials(db, tenant_id=str(tenant_id), conversation_id="diagnostic")
    if not active_provider:
        return {"ok": False, "status": "missing_active_provider", "message": "Nenhum provider Meta ativo com token e phone_number_id foi resolvido pelo worker."}

    token = active_provider["token"]
    phone_number_id = active_provider["phone_number_id"]
    provider_id = active_provider["provider_id"]
    context = {"tenant_id": str(tenant_id), "provider_id": provider_id, "token_length": len(token or "")}

    async def _run_checks() -> dict:
        client = MetaCloudClient(token)
        me = await client.get("/me", params={"fields": "id,name"}, context={**context, "graph_check": "me"})
        phone = await client.get(
            f"/{phone_number_id}",
            params={"fields": "verified_name,display_phone_number,quality_rating,status"},
            context={**context, "graph_check": "phone_number"},
        )
        return {"me": me, "phone": phone}

    logger.info(
        "[SEND WORKER PROVIDER] provider_id=%s provider_name=%s token_exists=%s token_length=%s phone_number_id=%s action=diagnostic",
        provider_id,
        active_provider.get("provider_name"),
        bool(token),
        len(token or ""),
        phone_number_id,
    )
    try:
        checks = asyncio.run(_run_checks())
    except MetaApiError as exc:
        return {
            "ok": False,
            "status": "invalid_token" if exc.status_code == 401 else "meta_error",
            "provider_id": provider_id,
            "phone_number_id": phone_number_id,
            "token_exists": bool(token),
            "token_length": len(token or ""),
            "status_code": exc.status_code,
            "message": str(exc),
        }

    return {
        "ok": True,
        "status": "valid",
        "provider_id": provider_id,
        "provider_name": active_provider.get("provider_name"),
        "phone_number_id": phone_number_id,
        "token_exists": bool(token),
        "token_length": len(token or ""),
        "me": checks["me"],
        "phone": checks["phone"],
    }

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
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s is_active=%s updated_at=%s token_exists=%s token_length=%s action=test_connection",
        provider.id,
        provider.is_active,
        provider.updated_at.isoformat() if provider.updated_at else None,
        bool(token),
        len(token or ""),
    )
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
            secret_value = mapped.pop(source)
            if secret_value is None or str(secret_value).strip() == "":
                continue
            mapped[target] = encrypt_secret(secret_value)
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
    context = {"tenant_id": tenant_id, "provider_id": str(provider.id), "token_length": len(token or "")}
    me = await client.get("/me", params={"fields": "id,name"}, context={**context, "graph_check": "me"})
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s is_active=%s updated_at=%s graph_endpoint=/me status=valid meta_subject_id=%s",
        provider.id,
        provider.is_active,
        provider.updated_at.isoformat() if provider.updated_at else None,
        me.get("id") if isinstance(me, dict) else None,
    )
    phone = await client.get(
        f"/{provider.phone_number_id}",
        params={"fields": "verified_name,display_phone_number,quality_rating,status"},
        context={**context, "graph_check": "phone_number"},
    )
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s is_active=%s updated_at=%s graph_endpoint=/%s status=valid",
        provider.id,
        provider.is_active,
        provider.updated_at.isoformat() if provider.updated_at else None,
        provider.phone_number_id,
    )
    waba = await client.get(f"/{provider.waba_id}", params={"fields": "name,message_template_namespace"}, context=context)
    business = await client.get(f"/{provider.business_id}", params={"fields": "name"}, context=context)
    return {
        "meta_token_subject_id": me.get("id") if isinstance(me, dict) else None,
        "meta_token_subject_name": me.get("name") if isinstance(me, dict) else None,
        "verified_name": phone.get("verified_name"),
        "display_phone_number": phone.get("display_phone_number"),
        "quality_rating": phone.get("quality_rating"),
        "phone_status": phone.get("status"),
        "messaging_limit_tier": phone.get("messaging_limit_tier") or phone.get("quality_rating"),
        "business_name": business.get("name"),
        "waba_name": waba.get("name"),
        "last_sync_at": datetime.utcnow().isoformat(),
    }
