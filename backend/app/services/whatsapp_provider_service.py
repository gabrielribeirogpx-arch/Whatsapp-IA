from datetime import datetime
from uuid import UUID
import asyncio
import logging
import os

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.whatsapp_credentials_service import (
    WhatsAppCredentialsNotConfiguredError,
    get_tenant_whatsapp_credentials,
)
from app.services.whatsapp_message_service import (
    resolve_active_meta_provider_credentials,
)
from app.utils.encryption import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

SUPPORTED_CONNECTION_STATUSES = {
    "connected",
    "token_expired",
    "invalid_token",
    "invalid_phone_number",
    "meta_error",
    "disconnected",
}


PROVIDER_REQUIRED_FIELDS = {
    "meta_cloud": [
        "waba_id",
        "phone_number_id",
        "business_id",
        "access_token_encrypted",
    ],
    "bsp_360dialog": ["api_key_encrypted", "phone_number_id"],
}


class DuplicatePhoneNumberProviderError(ValueError):
    """Raised when a WhatsApp phone_number_id is already owned by another tenant/provider."""

    def __init__(
        self,
        reason: str,
        *,
        provider_id: object | None = None,
        tenant_id: object | None = None,
        phone_number_id: object | None = None,
        validation: str | None = None,
        hidden_provider: bool | None = None,
        soft_delete: bool | None = None,
        ownership_migration: str | None = None,
        blocking_provider: dict | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.provider_id = str(provider_id) if provider_id is not None else None
        self.tenant_id = str(tenant_id) if tenant_id is not None else None
        self.phone_number_id = (
            str(phone_number_id) if phone_number_id is not None else None
        )
        self.validation = validation
        self.hidden_provider = hidden_provider
        self.soft_delete = soft_delete
        self.ownership_migration = ownership_migration
        self.blocking_provider = blocking_provider or {}

    def to_dict(self) -> dict:
        payload = {
            "reason": self.reason,
            "provider_id": self.provider_id,
            "tenant_id": self.tenant_id,
            "phone_number_id": self.phone_number_id,
        }
        if self.validation is not None:
            payload["validation"] = self.validation
        if self.hidden_provider is not None:
            payload["hidden_provider"] = self.hidden_provider
        if self.soft_delete is not None:
            payload["soft_delete"] = self.soft_delete
        if self.ownership_migration is not None:
            payload["ownership_migration"] = self.ownership_migration
        if self.blocking_provider:
            payload["blocking_provider"] = self.blocking_provider
        return payload


def _provider_deleted_at(provider: TenantWhatsAppProvider | None):
    if not provider:
        return None
    return getattr(provider, "deleted_at", None)


def _provider_conflict_log_row(provider: TenantWhatsAppProvider | None) -> dict | None:
    if not provider:
        return None
    deleted_at = _provider_deleted_at(provider)
    return {
        "provider_id": str(provider.id),
        "tenant_id": str(provider.tenant_id),
        "provider": provider.provider_type,
        "name": provider.display_name,
        "phone_number_id": provider.phone_number_id,
        "waba_id": provider.waba_id,
        "business_id": provider.business_id,
        "is_active": provider.is_active,
        "status": provider.status,
        "connection_status": getattr(provider, "connection_status", provider.status),
        "last_validation_at": provider.last_validation_at.isoformat() if getattr(provider, "last_validation_at", None) else None,
        "last_validation_error": getattr(provider, "last_validation_error", None),
        "deleted_at": deleted_at.isoformat() if deleted_at else None,
    }


def _provider_list_log_row(provider: TenantWhatsAppProvider) -> dict:
    deleted_at = _provider_deleted_at(provider)
    return {
        "provider_id": str(provider.id),
        "tenant_id": str(provider.tenant_id),
        "provider_type": provider.provider_type,
        "display_name": provider.display_name,
        "is_active": provider.is_active,
        "status": provider.status,
        "connection_status": getattr(provider, "connection_status", provider.status),
        "phone_number_id": provider.phone_number_id,
        "waba_id": provider.waba_id,
        "business_id": provider.business_id,
        "deleted_at": deleted_at.isoformat() if deleted_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def _provider_list_filter_state() -> dict:
    deleted_at_column = getattr(TenantWhatsAppProvider, "deleted_at", None)
    return {
        "tenant_id": "exact",
        "is_active": "not_applied",
        "deleted_at": "IS NULL" if deleted_at_column is not None else "not_mapped",
        "provider_type": "not_applied",
    }


def _apply_not_deleted_filter(query):
    deleted_at_column = getattr(TenantWhatsAppProvider, "deleted_at", None)
    if deleted_at_column is not None:
        query = query.where(deleted_at_column.is_(None))
    return query


def _find_provider_conflict(db: Session, *conditions):
    query = select(TenantWhatsAppProvider).where(*conditions)
    query = _apply_not_deleted_filter(query)
    return db.execute(query).scalars().first()


def _log_provider_create_conflict_check(
    db: Session, *, tenant_id: UUID, data: dict
) -> dict[str, TenantWhatsAppProvider | None]:
    provider = data.get("provider_type")
    name = str(data.get("display_name") or "").strip() or None
    phone_number_id = _clean_phone_number_id(data.get("phone_number_id")) or None
    waba_id = str(data.get("waba_id") or "").strip() or None

    existing_provider_by_phone = (
        _find_provider_conflict(
            db, TenantWhatsAppProvider.phone_number_id == phone_number_id
        )
        if phone_number_id
        else None
    )
    existing_provider_by_waba = (
        _find_provider_conflict(
            db,
            TenantWhatsAppProvider.waba_id == waba_id,
        )
        if waba_id
        else None
    )
    existing_provider_by_name = (
        _find_provider_conflict(
            db,
            TenantWhatsAppProvider.tenant_id == tenant_id,
            TenantWhatsAppProvider.display_name == name,
        )
        if name
        else None
    )

    conflicts = {
        "existing_provider_by_phone": existing_provider_by_phone,
        "existing_provider_by_waba": existing_provider_by_waba,
        "existing_provider_by_name": existing_provider_by_name,
    }
    logger.info(
        "[PROVIDER CREATE REQUEST] tenant_id=%s provider=%s name=%s phone_number_id=%s waba_id=%s",
        tenant_id,
        provider,
        name,
        phone_number_id,
        waba_id,
    )
    logger.info(
        "[PROVIDER CONFLICT CHECK] tenant_id=%s existing_provider_by_phone=%s existing_provider_by_waba=%s existing_provider_by_name=%s",
        tenant_id,
        _provider_conflict_log_row(existing_provider_by_phone),
        _provider_conflict_log_row(existing_provider_by_waba),
        _provider_conflict_log_row(existing_provider_by_name),
    )
    return conflicts


def _clean_phone_number_id(value: object) -> str:
    return str(value or "").strip()


def _assert_phone_number_id_available(
    db: Session,
    *,
    tenant_id: UUID,
    phone_number_id: object,
    provider_id: UUID | str | None = None,
    action: str = "validate",
) -> None:
    normalized = _clean_phone_number_id(phone_number_id)
    if not normalized:
        return

    query = select(TenantWhatsAppProvider).where(
        TenantWhatsAppProvider.phone_number_id == normalized
    )
    query = _apply_not_deleted_filter(query)
    if provider_id:
        query = query.where(TenantWhatsAppProvider.id != provider_id)

    conflict = db.execute(query).scalars().first()
    if not conflict:
        return

    validation = "whatsapp_provider_service._assert_phone_number_id_available"
    metadata = conflict.metadata_json or {}
    ownership_migration = metadata.get("remediation") or None
    hidden_provider = str(conflict.tenant_id) != str(tenant_id)
    deleted_at = _provider_deleted_at(conflict)
    soft_delete = deleted_at is not None
    blocking_provider = {
        "provider_id": str(conflict.id),
        "tenant_id": str(conflict.tenant_id),
        "provider_type": conflict.provider_type,
        "display_name": conflict.display_name,
        "phone_number_id": conflict.phone_number_id,
        "waba_id": conflict.waba_id,
        "business_id": conflict.business_id,
        "is_active": conflict.is_active,
        "status": conflict.status,
        "connection_status": getattr(conflict, "connection_status", conflict.status),
        "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
        "updated_at": conflict.updated_at.isoformat() if conflict.updated_at else None,
        "deleted_at": deleted_at.isoformat() if deleted_at else None,
        "metadata_remediation": ownership_migration,
    }
    reason = (
        f"phone_number_id={normalized} bloqueado pela validação {validation}: "
        f"já existe tenant_whatsapp_providers.id={conflict.id} "
        f"tenant_id={conflict.tenant_id} com o mesmo phone_number_id. "
        f"hidden_provider={hidden_provider}; soft_delete={soft_delete}; "
        f"provider_id={conflict.id}; is_active={conflict.is_active}; "
        f"deleted_at={deleted_at.isoformat() if deleted_at else None}; "
        f"ownership_migration={ownership_migration or 'not_detected'}."
        + (
            " Provider inativo encontrado: reative/atualize o provider existente "
            "em vez de criar outra conexão com o mesmo phone_number_id."
            if not conflict.is_active
            else ""
        )
    )
    logger.warning(
        "[PROVIDER PHONE NUMBER CONFLICT] requested_tenant_id=%s requested_provider_id=%s phone_number_id=%s existing_provider_id=%s existing_tenant_id=%s existing_status=%s existing_is_active=%s validation=%s hidden_provider=%s soft_delete=%s ownership_migration=%s",
        tenant_id,
        provider_id,
        normalized,
        conflict.id,
        conflict.tenant_id,
        conflict.status,
        conflict.is_active,
        validation,
        hidden_provider,
        soft_delete,
        ownership_migration,
    )
    if action == "create":
        logger.warning(
            "[PROVIDER CONFLICT REASON] provider_id=%s is_active=%s deleted_at=%s tenant_id=%s reason=%s",
            conflict.id,
            conflict.is_active,
            deleted_at.isoformat() if deleted_at else None,
            conflict.tenant_id,
            reason,
        )
        logger.warning(
            "[PROVIDER CREATE CONFLICT] provider_id=%s tenant_id=%s phone_number_id=%s reason=%s",
            conflict.id,
            conflict.tenant_id,
            normalized,
            reason,
        )
    raise DuplicatePhoneNumberProviderError(
        reason,
        provider_id=conflict.id,
        tenant_id=conflict.tenant_id,
        phone_number_id=normalized,
        validation=validation,
        hidden_provider=hidden_provider,
        soft_delete=soft_delete,
        ownership_migration=ownership_migration or "not_detected",
        blocking_provider=blocking_provider,
    )



def _classify_meta_error(exc: MetaApiError, *, endpoint: str | None = None) -> str:
    message = str(exc).lower()
    payload = getattr(exc, "payload", {}) or {}
    raw = ""
    if isinstance(payload, dict):
        raw = str(payload.get("raw") or payload.get("error") or "").lower()
    combined = f"{message} {raw} {endpoint or ''}"
    if exc.status_code == 401:
        return "token_expired"
    if "phone_number_id" in combined or "phone number" in combined:
        return "invalid_phone_number"
    return "meta_error"


def _set_provider_connection_status(
    provider: TenantWhatsAppProvider,
    status: str,
    *,
    error_message: str | None = None,
    checked_at: datetime | None = None,
) -> None:
    normalized = status if status in SUPPORTED_CONNECTION_STATUSES else "meta_error"
    now = checked_at or datetime.utcnow()
    provider.connection_status = normalized
    provider.status = normalized
    provider.last_validation_at = now
    provider.last_connection_check_at = now
    provider.last_validation_error = error_message
    if error_message:
        provider.metadata_json = {**(provider.metadata_json or {}), "last_error": error_message}
    elif provider.metadata_json:
        metadata = dict(provider.metadata_json or {})
        metadata.pop("last_error", None)
        provider.metadata_json = metadata


def record_provider_meta_error(
    db: Session,
    provider: TenantWhatsAppProvider,
    exc: MetaApiError,
    *,
    endpoint: str | None = None,
) -> str:
    status = _classify_meta_error(exc, endpoint=endpoint)
    _set_provider_connection_status(provider, status, error_message=str(exc))
    provider.updated_at = datetime.utcnow()
    db.add(provider)
    db.commit()
    return status


def record_provider_meta_error_by_id(
    db: Session,
    *,
    provider_id: UUID | str | None,
    exc: MetaApiError,
    endpoint: str | None = None,
) -> str | None:
    if not provider_id:
        return None
    provider = (
        db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id))
        .scalars()
        .first()
    )
    if not provider:
        return None
    return record_provider_meta_error(db, provider, exc, endpoint=endpoint)

def _log_provider_save(*, provider: TenantWhatsAppProvider, action: str) -> None:
    logger.info(
        "[PROVIDER SAVE] action=%s provider_id=%s provider_type=%s business_id=%s waba_id=%s phone_number_id=%s",
        action,
        provider.id,
        provider.provider_type,
        provider.business_id,
        provider.waba_id,
        provider.phone_number_id,
    )


def list_providers(db: Session, tenant_id: UUID):
    filter_state = _provider_list_filter_state()
    logger.info(
        "[WHATSAPP PROVIDERS LIST QUERY] tenant_id=%s filters=%s",
        tenant_id,
        filter_state,
    )

    base_query = select(TenantWhatsAppProvider).where(
        TenantWhatsAppProvider.tenant_id == tenant_id
    )
    tenant_providers = db.execute(base_query).scalars().all()

    list_query = _apply_not_deleted_filter(base_query).order_by(
        TenantWhatsAppProvider.is_active.desc(),
        TenantWhatsAppProvider.updated_at.desc(),
        TenantWhatsAppProvider.created_at.desc(),
    )
    providers = db.execute(list_query).scalars().all()

    listed_provider_ids = {str(provider.id) for provider in providers}
    hidden_providers = [
        provider
        for provider in tenant_providers
        if str(provider.id) not in listed_provider_ids
    ]
    for provider in hidden_providers:
        logger.warning(
            "[PROVIDER HIDDEN FROM LIST] tenant_id=%s filters=%s provider=%s",
            tenant_id,
            filter_state,
            _provider_list_log_row(provider),
        )

    logger.info(
        "[WHATSAPP PROVIDERS LIST RESULT] count=%s provider_ids=%s",
        len(providers),
        [str(provider.id) for provider in providers],
    )
    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_count=%s active_count=%s providers=%s",
        tenant_id,
        "n/a",
        len(providers),
        sum(1 for provider in providers if provider.is_active),
        [_provider_list_log_row(provider) for provider in providers],
    )
    return providers


def create_provider(db: Session, tenant_id: UUID, payload):
    try:
        data = payload.model_dump(exclude_unset=True)
        _log_provider_create_conflict_check(db, tenant_id=tenant_id, data=data)
        _assert_phone_number_id_available(
            db,
            tenant_id=tenant_id,
            phone_number_id=data.get("phone_number_id"),
            action="create",
        )
        provider = TenantWhatsAppProvider(
            tenant_id=tenant_id, **_normalize_secret_fields(data)
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        _log_provider_save(provider=provider, action="create")
        return provider
    except Exception:
        db.rollback()
        raise


def update_provider(db: Session, tenant_id: UUID, provider_id: UUID, payload):
    provider = _get_provider(db, tenant_id, provider_id)
    incoming = payload.model_dump(exclude_unset=True)
    if "phone_number_id" in incoming:
        _assert_phone_number_id_available(
            db,
            tenant_id=tenant_id,
            phone_number_id=incoming.get("phone_number_id"),
            provider_id=provider.id,
        )
    token_was_updated = (
        "access_token" in incoming
        and str(incoming.get("access_token") or "").strip() != ""
    )
    for secret_field in ("access_token", "app_secret", "api_key"):
        if secret_field in incoming and (
            incoming[secret_field] is None or str(incoming[secret_field]).strip() == ""
        ):
            incoming.pop(secret_field, None)
    for key, value in _normalize_secret_fields(incoming).items():
        if value is None:
            continue
        setattr(provider, key, value)
    if (
        token_was_updated
        and provider.is_active
        and provider.provider_type == "meta_cloud"
    ):
        _set_provider_connection_status(provider, "disconnected", error_message=None)
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
    _log_provider_save(provider=provider, action="update")
    return provider


def set_active_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    _assert_phone_number_id_available(
        db,
        tenant_id=tenant_id,
        phone_number_id=provider.phone_number_id,
        provider_id=provider.id,
    )
    db.execute(
        update(TenantWhatsAppProvider)
        .where(TenantWhatsAppProvider.tenant_id == tenant_id)
        .values(is_active=False)
    )
    provider.is_active = True
    _set_provider_connection_status(provider, "connected", error_message=None)
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
    active_provider = resolve_active_meta_provider_credentials(
        db, tenant_id=str(tenant_id), conversation_id="diagnostic"
    )
    if not active_provider:
        return {
            "ok": False,
            "status": "missing_active_provider",
            "message": "Nenhum provider Meta ativo com token e phone_number_id foi resolvido pelo worker.",
        }

    token = active_provider["token"]
    phone_number_id = active_provider["phone_number_id"]
    provider_id = active_provider["provider_id"]
    context = {
        "tenant_id": str(tenant_id),
        "provider_id": provider_id,
        "token_length": len(token or ""),
    }

    async def _run_checks() -> dict:
        client = MetaCloudClient(token)
        me = await client.get(
            "/me",
            params={"fields": "id,name"},
            context={**context, "graph_check": "me"},
        )
        phone = await client.get(
            f"/{phone_number_id}",
            params={
                "fields": "verified_name,display_phone_number,quality_rating,status"
            },
            context={**context, "graph_check": "phone_number"},
        )
        return {"me": me, "phone": phone}

    logger.info(
        "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s action=diagnostic",
        provider_id,
        tenant_id,
        active_provider.get("provider_name"),
        phone_number_id,
        active_provider.get("waba_id"),
        active_provider.get("business_id"),
        active_provider.get("status"),
        active_provider.get("is_active"),
        bool(token),
        len(token or ""),
    )
    try:
        checks = asyncio.run(_run_checks())
    except MetaApiError as exc:
        status = record_provider_meta_error_by_id(db, provider_id=provider_id, exc=exc, endpoint="worker_diagnostic") or ("token_expired" if exc.status_code == 401 else "meta_error")
        return {
            "ok": False,
            "status": status,
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


def runtime_send_diagnostics(db: Session, tenant_id: UUID) -> dict:
    active_provider = resolve_active_meta_provider_credentials(
        db, tenant_id=str(tenant_id), conversation_id="runtime-send-diagnostic"
    )
    source = "provider"
    provider_id = None
    provider_name = None
    phone_number_id = None
    waba_id = None
    business_id = None
    status = None
    is_active = None

    if active_provider:
        token = active_provider["token"]
        provider_id = active_provider["provider_id"]
        provider_name = active_provider.get("provider_name")
        phone_number_id = active_provider["phone_number_id"]
        waba_id = active_provider.get("waba_id")
        business_id = active_provider.get("business_id")
        status = active_provider.get("status")
        is_active = active_provider.get("is_active")
    else:
        source = "legacy"
        try:
            credentials = get_tenant_whatsapp_credentials(str(tenant_id))
        except WhatsAppCredentialsNotConfiguredError:
            return {
                "provider_id": None,
                "tenant_id": str(tenant_id),
                "phone_number_id": None,
                "waba_id": None,
                "business_id": None,
                "token_valid": False,
                "source": source,
                "meta_response": {"error": "missing_whatsapp_credentials"},
            }
        token = credentials["token"]
        phone_number_id = credentials["phone_number_id"]
        provider_name = "legacy_credentials"
        status = "legacy"
        is_active = False

    logger.info(
        "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s source=%s action=runtime_send_diagnostic",
        provider_id,
        tenant_id,
        provider_name,
        phone_number_id,
        waba_id,
        business_id,
        status,
        is_active,
        bool(token),
        len(token or ""),
        source,
    )

    async def _run_checks() -> dict:
        client = MetaCloudClient(token)
        context = {
            "tenant_id": str(tenant_id),
            "provider_id": provider_id,
            "token_length": len(token or ""),
            "source": source,
        }
        me = await client.get(
            "/me",
            params={"fields": "id,name"},
            context={**context, "graph_check": "me"},
        )
        phone = await client.get(
            f"/{phone_number_id}",
            params={
                "fields": "verified_name,display_phone_number,quality_rating,status"
            },
            context={**context, "graph_check": "phone_number"},
        )
        return {"me": me, "phone_number": phone}

    try:
        meta_response = asyncio.run(_run_checks())
        token_valid = True
    except MetaApiError as exc:
        if provider_id:
            record_provider_meta_error_by_id(db, provider_id=provider_id, exc=exc, endpoint="runtime_send_diagnostic")
        meta_response = {
            "error": str(exc),
            "status_code": exc.status_code,
            "payload": exc.payload,
        }
        token_valid = False

    return {
        "provider_id": provider_id,
        "tenant_id": str(tenant_id),
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "business_id": business_id,
        "token_valid": token_valid,
        "source": source,
        "meta_response": meta_response,
    }


def delete_provider(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    db.delete(provider)
    db.commit()


def test_provider_connection(db: Session, tenant_id: UUID, provider_id: UUID):
    provider = _get_provider(db, tenant_id, provider_id)
    required = PROVIDER_REQUIRED_FIELDS.get(provider.provider_type, ["phone_number_id"])
    missing = [field for field in required if not getattr(provider, field)]
    if missing:
        connection_status = (
            "invalid_phone_number"
            if "phone_number_id" in missing
            else "invalid_token"
            if any(field in missing for field in ("access_token_encrypted", "api_key_encrypted"))
            else "disconnected"
        )
        message = f"Campos obrigatórios ausentes: {', '.join(missing)}"
        _set_provider_connection_status(provider, connection_status, error_message=message)
        db.commit()
        return {"ok": False, "status": provider.connection_status, "message": message}

    if not os.getenv("WHATSAPP_SECRET_ENCRYPTION_KEY", "").strip():
        message = "WHATSAPP_SECRET_ENCRYPTION_KEY não configurada."
        _set_provider_connection_status(provider, "invalid_token", error_message=message)
        db.commit()
        return {"ok": False, "status": provider.connection_status, "message": message}

    if provider.provider_type != "meta_cloud":
        _set_provider_connection_status(provider, "connected", error_message=None)
        db.commit()
        return {
            "ok": True,
            "status": provider.connection_status,
            "message": "Conexão validada para provider não-Meta.",
        }

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
        message = "Token inválido ou ausente."
        _set_provider_connection_status(provider, "invalid_token", error_message=message)
        db.commit()
        return {"ok": False, "status": provider.connection_status, "message": message}

    try:
        metadata = asyncio.run(
            _sync_meta_provider_metadata(provider, token, str(tenant_id))
        )
        provider.metadata_json = {**(provider.metadata_json or {}), **metadata}
        _set_provider_connection_status(provider, "connected", error_message=None)
        db.commit()
        return {
            "ok": True,
            "status": provider.connection_status,
            "message": "Conexão Meta validada com sucesso.",
            "metadata": metadata,
        }
    except MetaApiError as exc:
        connection_status = record_provider_meta_error(db, provider, exc, endpoint="metadata_validation")
        return {"ok": False, "status": connection_status, "message": str(exc)}

def _normalize_secret_fields(data: dict):
    mapped = dict(data)
    if "phone_number_id" in mapped and mapped["phone_number_id"] is not None:
        mapped["phone_number_id"] = (
            _clean_phone_number_id(mapped["phone_number_id"]) or None
        )
    for source, target in (
        ("access_token", "access_token_encrypted"),
        ("app_secret", "app_secret_encrypted"),
        ("api_key", "api_key_encrypted"),
    ):
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
    provider = (
        db.execute(
            select(TenantWhatsAppProvider).where(
                TenantWhatsAppProvider.id == provider_id,
                TenantWhatsAppProvider.tenant_id == tenant_id,
            )
        )
        .scalars()
        .first()
    )
    if not provider:
        raise ValueError("Provider não encontrado")
    return provider


async def _sync_meta_provider_metadata(
    provider: TenantWhatsAppProvider, token: str, tenant_id: str
) -> dict:
    client = MetaCloudClient(token)
    context = {
        "tenant_id": tenant_id,
        "provider_id": str(provider.id),
        "token_length": len(token or ""),
    }
    me = await client.get(
        "/me", params={"fields": "id,name"}, context={**context, "graph_check": "me"}
    )
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
    waba = await client.get(
        f"/{provider.waba_id}",
        params={"fields": "name,message_template_namespace"},
        context=context,
    )
    business = await client.get(
        f"/{provider.business_id}", params={"fields": "name"}, context=context
    )
    return {
        "meta_token_subject_id": me.get("id") if isinstance(me, dict) else None,
        "meta_token_subject_name": me.get("name") if isinstance(me, dict) else None,
        "verified_name": phone.get("verified_name"),
        "display_phone_number": phone.get("display_phone_number"),
        "quality_rating": phone.get("quality_rating"),
        "phone_status": phone.get("status"),
        "messaging_limit_tier": phone.get("messaging_limit_tier")
        or phone.get("quality_rating"),
        "business_name": business.get("name"),
        "waba_name": waba.get("name"),
        "last_sync_at": datetime.utcnow().isoformat(),
    }
