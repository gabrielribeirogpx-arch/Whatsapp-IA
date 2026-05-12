from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.whatsapp_business import WhatsAppTemplateCreate, WhatsAppTemplateOut, WhatsAppTemplateUpdate
from app.services import whatsapp_template_service
from app.services.tenant_service import get_current_tenant
from app.services.whatsapp_message_service import send_template_message
from app.services.whatsapp_template_service import TemplateSubmitError

router = APIRouter(tags=["whatsapp-templates"])

@router.get("", response_model=list[WhatsAppTemplateOut])
def get_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    return whatsapp_template_service.list_templates(db, tenant.id)

@router.post("", response_model=WhatsAppTemplateOut)
def create_template(payload: WhatsAppTemplateCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP TEMPLATE CREATE]", f"tenant_id={tenant.id}", f"provider_id={payload.provider_id}")
    return whatsapp_template_service.create_template(db, tenant.id, payload)

@router.patch("/{template_id}", response_model=WhatsAppTemplateOut)
def patch_template(template_id: str, payload: WhatsAppTemplateUpdate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        return whatsapp_template_service.update_template(db, tenant.id, template_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/{template_id}", status_code=204)
def remove_template(template_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        whatsapp_template_service.delete_template(db, tenant.id, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/{template_id}/submit", response_model=WhatsAppTemplateOut)
def submit_template(template_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print(f"[WHATSAPP TEMPLATE SUBMIT ROUTE HIT] template_id={template_id}")
    print("[WHATSAPP TEMPLATE SUBMIT]", f"tenant_id={tenant.id}", f"template_id={template_id}")
    try:
        return whatsapp_template_service.submit_template_placeholder(db, tenant.id, template_id)
    except TemplateSubmitError as exc:
        detail = {"detail": exc.detail}
        if exc.meta_error:
            detail["meta_error"] = exc.meta_error
        if exc.meta_code:
            detail["meta_code"] = exc.meta_code
        return JSONResponse(status_code=exc.status_code, content=detail)

@router.post("/sync")
def sync_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP TEMPLATE SYNC]", f"tenant_id={tenant.id}")
    return whatsapp_template_service.sync_templates_placeholder(db, tenant.id)


@router.post("/{template_id}/test-send")
def test_send_template(template_id: str, payload: dict[str, Any], db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    provider_id = str(payload.get("provider_id") or "").strip()
    to = str(payload.get("to") or "").strip()
    variables = payload.get("variables") or {}

    if not provider_id or not to:
        raise HTTPException(status_code=400, detail="provider_id e to são obrigatórios")

    print("[WHATSAPP TEMPLATE TEST SEND]", f"tenant_id={tenant.id}", f"provider_id={provider_id}", f"template_id={template_id}", f"to={to}")
    print("[WHATSAPP TEMPLATE TEST PAYLOAD]", {"to": to, "type": "template", "template_id": template_id, "variables": variables})

    try:
        result = send_template_message(
            db,
            tenant_id=str(tenant.id),
            provider_id=provider_id,
            template_id=template_id,
            to=to,
            variables=variables,
        )
        print("[WHATSAPP TEMPLATE TEST RESPONSE]", {"provider_message_id": result.get("provider_message_id"), "raw": result.get("raw")})
        return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MetaApiError as exc:
        err = exc.payload.get("error") if isinstance(exc.payload, dict) else {}
        meta_message = err.get("message") if isinstance(err, dict) else None
        meta_code = err.get("code") if isinstance(err, dict) else None
        detail = str(exc)
        sandbox_hint = ""
        normalized = (meta_message or "").lower()
        if "recipient phone number not in allowed list" in normalized or "allowed list" in normalized or "not a valid whatsapp user" in normalized:
            sandbox_hint = " Número não autorizado no ambiente de teste da Meta (adicione o número em WhatsApp > API Setup > To)."
        return JSONResponse(status_code=exc.status_code, content={
            "detail": f"{detail}{sandbox_hint}",
            "meta_error": meta_message or detail,
            "meta_code": meta_code,
        })

