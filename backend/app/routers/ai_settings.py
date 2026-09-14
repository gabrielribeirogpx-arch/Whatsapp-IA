import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.tenant_ai_setting import TenantAISetting
from app.models.user import TenantUser
from app.routers.account import get_current_user
from app.security.workspace_rbac import WorkspacePermission
from app.services.administrative_audit import require_administrative_permission
from app.services.audit_service import write_audit_log
from app.schemas.ai_settings import TenantAISettingsOut, TenantAISettingsTestOut, TenantAISettingsTestRequest, TenantAISettingsUpdate
from app.services.ai_model_validation import validate_chat_model, validate_embedding_model
from app.services.llm_service import LLMConfigurationError, LLMGenerationError, test_provider_connection
from app.services.tenant_service import get_current_tenant
from app.utils.encryption import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/ai/settings", tags=["ai-settings"])
logger = logging.getLogger(__name__)


def _get_settings(db: Session, tenant_id):
    return db.execute(select(TenantAISetting).where(TenantAISetting.tenant_id == tenant_id)).scalars().first()


def _to_out(tenant_id, setting: TenantAISetting | None) -> TenantAISettingsOut:
    if not setting:
        return TenantAISettingsOut(tenant_id=tenant_id, provider="wazza_default", chat_model=None, has_api_key=False)
    return TenantAISettingsOut(
        tenant_id=setting.tenant_id,
        provider=setting.provider,
        chat_model=setting.chat_model,
        temperature=float(setting.temperature or 0.2),
        max_tokens=int(setting.max_tokens or 1200),
        embedding_provider=setting.embedding_provider,
        embedding_model=setting.embedding_model,
        is_enabled=bool(setting.is_enabled),
        has_api_key=bool(decrypt_secret(setting.encrypted_api_key) if setting.encrypted_api_key else False),
    )


@router.get("", response_model=TenantAISettingsOut)
def get_ai_settings(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return _to_out(tenant.id, _get_settings(db, tenant.id))


@router.put("", response_model=TenantAISettingsOut)
def update_ai_settings(request: Request, payload: TenantAISettingsUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    require_administrative_permission(db, user, WorkspacePermission.MANAGE_SETTINGS, request=request, action="ai_settings_updated", resource_type="ai_settings", resource_id=tenant.id)
    setting = _get_settings(db, tenant.id)
    if setting is None:
        setting = TenantAISetting(tenant_id=tenant.id)
        db.add(setting)
    setting.provider = payload.provider
    try:
        setting.chat_model = validate_chat_model(payload.chat_model)
        setting.embedding_model = validate_embedding_model(payload.embedding_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    setting.temperature = payload.temperature
    setting.max_tokens = payload.max_tokens
    setting.embedding_provider = payload.embedding_provider.strip() if payload.embedding_provider else None
    setting.is_enabled = payload.is_enabled
    if payload.api_key is not None and payload.api_key.strip():
        setting.encrypted_api_key = encrypt_secret(payload.api_key)
    db.flush()
    write_audit_log(db, action="ai_settings_updated", tenant_id=tenant.id, user_id=user.id, entity_type="ai_settings", entity_id=tenant.id, metadata={"provider": setting.provider, "chat_model": setting.chat_model, "embedding_provider": setting.embedding_provider, "embedding_model": setting.embedding_model, "is_enabled": setting.is_enabled, "temperature": float(setting.temperature), "max_tokens": setting.max_tokens, "api_key_changed": payload.api_key is not None}, request=request)
    db.commit(); db.refresh(setting)
    return _to_out(tenant.id, setting)


@router.post("/test", response_model=TenantAISettingsTestOut)
def test_ai_settings(payload: TenantAISettingsTestRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    setting = _get_settings(db, tenant.id)
    provider = payload.provider or (setting.provider if setting else "wazza_default")
    provider = provider.strip().lower()

    api_key = ""
    chat_model = None
    if provider == "wazza_default":
        try:
            chat_model = validate_chat_model(payload.chat_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        chat_model = payload.chat_model or (setting.chat_model if setting else None)
        try:
            chat_model = validate_chat_model(chat_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not chat_model:
            logger.warning("[AI SETTINGS TEST] validation_failed tenant_id=%s provider=%s reason=missing_chat_model", tenant.id, provider)
            raise HTTPException(status_code=400, detail="Selecione um modelo de conversação.")
        api_key = payload.api_key.strip() if payload.api_key else ""
        if not api_key and setting and setting.encrypted_api_key:
            api_key = decrypt_secret(setting.encrypted_api_key) or ""

    try:
        test_provider_connection(provider, api_key, chat_model=chat_model)
    except LLMConfigurationError as exc:
        logger.warning("[AI SETTINGS TEST] configuration_failed tenant_id=%s provider=%s model=%s reason=%s", tenant.id, provider, chat_model, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMGenerationError as exc:
        logger.warning("[AI SETTINGS TEST] provider_test_failed tenant_id=%s provider=%s model=%s reason=%s", tenant.id, provider, chat_model, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TenantAISettingsTestOut(ok=True, message="Conexão validada com sucesso.")


# This is an API handler, not a pytest test function when imported by tests.
test_ai_settings.__test__ = False


@router.delete("/key", response_model=TenantAISettingsOut)
def delete_ai_key(request: Request, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    require_administrative_permission(db, user, WorkspacePermission.MANAGE_SETTINGS, request=request, action="ai_credentials_rotated", resource_type="ai_settings", resource_id=tenant.id)
    setting = _get_settings(db, tenant.id)
    if setting is None:
        return _to_out(tenant.id, None)
    setting.encrypted_api_key = None
    db.flush()
    write_audit_log(db, action="ai_credentials_rotated", tenant_id=tenant.id, user_id=user.id, entity_type="ai_settings", entity_id=tenant.id, metadata={"credential": "api_key", "new_status": "removed"}, request=request)
    db.commit(); db.refresh(setting)
    return _to_out(tenant.id, setting)
