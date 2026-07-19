import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.schemas.settings import SettingsOut, SettingsUpdateIn
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)


def _serialize_settings(tenant: Tenant) -> SettingsOut:
    return SettingsOut(
        has_whatsapp_token=bool(tenant.whatsapp_token),
        phone_number_id=tenant.phone_number_id,
        system_name=tenant.name or "WhatsApp IA",
        language=tenant.language or "pt-BR",
        workspace_profile=tenant.workspace_profile or "private_sales",
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(request: Request, tenant: Tenant = Depends(get_current_tenant)):
    logger.info("event=settings_read tenant_id=%s", getattr(request.state, "tenant_id", None))
    return _serialize_settings(tenant)


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    request: Request,
    payload: SettingsUpdateIn,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    provided_fields = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    logger.info(
        "event=settings_update tenant_id=%s fields=%s has_whatsapp_token_update=%s",
        tenant_id,
        sorted(provided_fields),
        "whatsapp_token" in provided_fields or "token" in provided_fields,
    )
    try:
        disconnect_whatsapp = False

        if "whatsapp_token" in provided_fields or "token" in provided_fields:
            token_value = payload.whatsapp_token if "whatsapp_token" in provided_fields else payload.token
            normalized_token = token_value.strip() if isinstance(token_value, str) else token_value
            if normalized_token in (None, ""):
                tenant.whatsapp_token = None
                disconnect_whatsapp = True
                logger.info("event=whatsapp_token_cleared tenant_id=%s", tenant_id)
            else:
                tenant.whatsapp_token = normalized_token

        if "phone_number_id" in provided_fields:
            normalized_phone_number_id = payload.phone_number_id.strip() if isinstance(payload.phone_number_id, str) else payload.phone_number_id
            if normalized_phone_number_id in (None, ""):
                tenant.phone_number_id = None
                disconnect_whatsapp = True
                print("[SETTINGS CLEAR FIELD]", "field=phone_number_id", f"tenant_id={tenant_id}")
            else:
                tenant.phone_number_id = normalized_phone_number_id

        if payload.webhook_url is not None:
            tenant.webhook_url = payload.webhook_url.strip() or None

        if payload.webhook_status is not None:
            tenant.webhook_status = payload.webhook_status.strip() or "inactive"

        if disconnect_whatsapp:
            tenant.webhook_status = "inactive"
            logger.info("event=whatsapp_disconnected tenant_id=%s", tenant_id)

        if payload.system_name is not None:
            tenant.name = payload.system_name.strip()

        if payload.language is not None:
            tenant.language = payload.language.strip()

        if payload.workspace_profile is not None:
            tenant.workspace_profile = payload.workspace_profile

        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        if disconnect_whatsapp:
            logger.info("event=settings_disconnected tenant_id=%s", tenant_id)
    except IntegrityError as error:
        db.rollback()
        logger.warning("event=settings_update_integrity_error tenant_id=%s", tenant_id)
        constraint_name = ""
        if getattr(error, "orig", None) is not None:
            constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", "") or ""

        message = str(error)
        if "ix_tenants_phone_number_id" in constraint_name or "ix_tenants_phone_number_id" in message:
            raise HTTPException(
                status_code=409,
                detail="Este Phone Number ID já está vinculado a outro tenant. Use outro número ou desvincule do tenant anterior.",
            ) from error
        raise
    except Exception as error:
        db.rollback()
        logger.exception("event=settings_update_error tenant_id=%s", tenant_id)
        raise

    return _serialize_settings(tenant)
