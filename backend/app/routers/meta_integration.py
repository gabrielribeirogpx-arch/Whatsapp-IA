from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.tenant_service import get_current_tenant
from app.utils.encryption import encrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations/meta", tags=["meta-integration"])

ConnectionType = Literal["cloud_api", "cloud_api_coexistence"]
VALID_CONNECTION_TYPES = {"cloud_api", "cloud_api_coexistence"}
STATE_TTL_SECONDS = 15 * 60


def _state_secret() -> bytes:
    return (os.getenv("OAUTH_STATE_SECRET") or os.getenv("SECRET_KEY") or os.getenv("WHATSAPP_SECRET_ENCRYPTION_KEY") or "dev-state-secret").encode()


def _normalize_connection_type(value: object) -> ConnectionType:
    candidate = str(value or "cloud_api").strip()
    if candidate not in VALID_CONNECTION_TYPES:
        raise HTTPException(status_code=400, detail="connection_type inválido")
    return candidate  # type: ignore[return-value]


def create_meta_oauth_state(tenant_id: object, *, connection_type: ConnectionType = "cloud_api", nonce: str | None = None, issued_at: int | None = None) -> str:
    payload = {"tenant_id": str(tenant_id), "provider": "meta", "connection_type": connection_type, "nonce": nonce or secrets.token_urlsafe(24), "iat": issued_at or int(datetime.utcnow().timestamp())}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(hmac.new(_state_secret(), payload_b64.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def verify_meta_oauth_state(state: str) -> dict[str, Any]:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
        expected = hmac.new(_state_secret(), payload_b64.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="State Meta inválido") from exc
    if int(datetime.utcnow().timestamp()) - int(payload.get("iat", 0)) > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="State Meta expirado")
    if payload.get("provider") != "meta" or not payload.get("tenant_id"):
        raise HTTPException(status_code=400, detail="State Meta inválido")
    payload["connection_type"] = _normalize_connection_type(payload.get("connection_type"))
    return payload


def _connect_url(state: str) -> str:
    base_url = os.getenv("META_EMBEDDED_SIGNUP_URL", "https://www.facebook.com/dialog/oauth")
    params = {
        "client_id": os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID") or "",
        "redirect_uri": os.getenv("META_REDIRECT_URI") or os.getenv("BACKEND_PUBLIC_URL", "").rstrip("/") + "/api/integrations/meta/callback",
        "state": state,
        "scope": os.getenv("META_EMBEDDED_SIGNUP_SCOPES", "whatsapp_business_management,whatsapp_business_messaging,business_management"),
    }
    return f"{base_url}?{urlencode({k: v for k, v in params.items() if v})}"


def _provider_status(provider: TenantWhatsAppProvider | None) -> dict[str, Any]:
    meta = (provider.metadata_json or {}) if provider else {}
    return {
        "connected": bool(provider and provider.connection_status == "connected"),
        "provider_id": str(provider.id) if provider else None,
        "phone_number_id": provider.phone_number_id if provider else None,
        "display_phone_number": (provider.phone_display_name or meta.get("display_phone_number")) if provider else None,
        "waba_id": provider.waba_id if provider else None,
        "business_id": provider.business_id if provider else None,
        "connection_type": getattr(provider, "connection_type", None) or "cloud_api" if provider else "cloud_api",
        "coexistence_enabled": bool(getattr(provider, "coexistence_enabled", False)) if provider else False,
        "coexistence_status": getattr(provider, "coexistence_status", None) if provider else None,
        "status": provider.connection_status if provider else "disconnected",
        "account": meta.get("meta_token_subject_name") or meta.get("business_name") or meta.get("waba_name"),
        "name": provider.display_name if provider else None,
    }


@router.get("/status")
def get_meta_status(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant.id, TenantWhatsAppProvider.provider_type == "meta_cloud").order_by(TenantWhatsAppProvider.is_active.desc(), TenantWhatsAppProvider.updated_at.desc())).scalars().first()
    return _provider_status(provider)


@router.api_route("/connect-url", methods=["GET", "POST"])
async def get_meta_connect_url(request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), connection_type: str | None = Query(default=None)):
    body: dict[str, Any] = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    normalized = _normalize_connection_type(body.get("connection_type") or connection_type)
    logger.info("META_CONNECT_URL_REQUESTED tenant_id=%s connection_type=%s", tenant.id, normalized)
    state = create_meta_oauth_state(tenant.id, connection_type=normalized)
    url = _connect_url(state)
    logger.info("META_CONNECT_URL_CREATED tenant_id=%s connection_type=%s state_present=%s", tenant.id, normalized, bool(state))
    return {"url": url, "state": state, "connection_type": normalized}


@router.get("/callback")
def meta_callback(request: Request, code: str | None = None, state: str | None = None, db: Session = Depends(get_db)):
    payload = verify_meta_oauth_state(state or "")
    connection_type = _normalize_connection_type(payload.get("connection_type"))
    tenant_id = uuid.UUID(str(payload["tenant_id"]))
    params = dict(request.query_params)
    logger.info("META_CALLBACK_RECEIVED tenant_id=%s connection_type=%s has_code=%s", tenant_id, connection_type, bool(code))
    phone_number_id = params.get("phone_number_id") or params.get("business_phone_number_id") or params.get("phone_number_id_selected")
    provider = TenantWhatsAppProvider(
        tenant_id=tenant_id,
        provider_type="meta_cloud",
        display_name=params.get("display_name") or params.get("phone_display_name") or "Meta Cloud API",
        waba_id=params.get("waba_id") or params.get("whatsapp_business_account_id"),
        phone_number_id=phone_number_id,
        business_phone_number_id=params.get("business_phone_number_id") or phone_number_id,
        business_id=params.get("business_id"),
        phone_display_name=params.get("phone_display_name") or params.get("display_phone_number"),
        phone_verified_name=params.get("phone_verified_name") or params.get("verified_name"),
        access_token_encrypted=encrypt_secret(params.get("access_token")) if params.get("access_token") else None,
        connection_type=connection_type,
        coexistence_enabled=connection_type == "cloud_api_coexistence",
        coexistence_status=params.get("coexistence_status"),
        onboarding_metadata={k: v for k, v in params.items() if k not in {"access_token", "code", "state"}},
        metadata_json={"onboarding_source": "meta_embedded_signup"},
        status="connected" if phone_number_id else "disconnected",
        connection_status="connected" if phone_number_id else "disconnected",
        is_active=bool(phone_number_id),
    )
    if provider.is_active:
        db.execute(update(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id).values(is_active=False))
    db.add(provider)
    db.commit()
    logger.info("META_CONNECTION_SAVED tenant_id=%s provider_id=%s connection_type=%s coexistence_enabled=%s phone_number_id=%s", tenant_id, provider.id, provider.connection_type, provider.coexistence_enabled, provider.phone_number_id)
    frontend = os.getenv("FRONTEND_URL", "").rstrip("/")
    if frontend:
        return RedirectResponse(f"{frontend}/dashboard/settings?tab=whatsapp-business&meta=connected")
    return {"ok": True, "provider_id": str(provider.id), "connection_type": provider.connection_type, "coexistence_enabled": provider.coexistence_enabled}


@router.post("/disconnect")
def disconnect_meta(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant.id, TenantWhatsAppProvider.provider_type == "meta_cloud").order_by(TenantWhatsAppProvider.is_active.desc(), TenantWhatsAppProvider.updated_at.desc())).scalars().first()
    if provider:
        provider.is_active = False
        provider.connection_status = "disconnected"
        provider.status = "disconnected"
        db.commit()
    return {"ok": True}
