from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import TenantResolution, get_current_tenant, get_current_tenant_resolution, resolve_current_tenant

PROVIDER = "google_calendar"
AUTH_TYPE = "oauth2"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "email",
    "profile",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_TTL_SECONDS = 10 * 60

router = APIRouter(prefix="/integrations/google-calendar", tags=["google-calendar-integration"])
logger = logging.getLogger(__name__)


def get_google_calendar_connect_tenant(
    resolution: TenantResolution | None = Depends(get_current_tenant_resolution),
) -> Tenant:
    if not resolution:
        raise HTTPException(status_code=400, detail="Tenant não identificado")
    logger.info(
        "event=google_calendar_connect_tenant_resolved tenant_id=%s source=%s",
        resolution.tenant.id,
        resolution.source,
    )
    return resolution.tenant


def _client_id() -> str:
    return (os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()


def _state_secret() -> bytes:
    secret = (os.getenv("GOOGLE_CALENDAR_STATE_SECRET") or os.getenv("SECRET_KEY") or os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="Segredo OAuth não configurado")
    return secret.encode("utf-8")


def _redirect_uri(request: Request) -> str:
    configured = (os.getenv("GOOGLE_CALENDAR_REDIRECT_URI") or os.getenv("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    return configured or str(request.url_for("google_calendar_callback"))


def create_oauth_state(tenant_id: uuid.UUID, *, nonce: str | None = None, issued_at: int | None = None) -> str:
    payload = {
        "tenant_id": str(tenant_id),
        "nonce": nonce or secrets.token_urlsafe(24),
        "iat": issued_at or int(datetime.utcnow().timestamp()),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    signature = hmac.new(_state_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def verify_oauth_state(state: str) -> dict[str, Any]:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="State OAuth inválido") from exc
    expected = hmac.new(_state_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    actual = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=400, detail="State OAuth inválido")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    issued_at = int(payload.get("iat", 0))
    if int(datetime.utcnow().timestamp()) - issued_at > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="State OAuth expirado")
    if not payload.get("tenant_id") or not payload.get("nonce"):
        raise HTTPException(status_code=400, detail="State OAuth inválido")
    return payload


def _exchange_code_for_tokens(code: str, redirect_uri: str) -> dict[str, Any]:
    if not _client_id() or not _client_secret():
        raise HTTPException(status_code=500, detail="Credenciais Google OAuth não configuradas")
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail="Falha ao trocar código OAuth")
    return response.json()


def _fetch_account_email(access_token: str) -> str | None:
    response = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail="Falha ao buscar conta Google")
    return response.json().get("email")


@router.get("/connect")
def connect_google_calendar(
    request: Request,
    tenant_slug: str | None = Query(None),
    tenant_id: str | None = Query(None),
    x_tenant_slug: str | None = Header(None, alias="X-Tenant-Slug"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_tenant_id_upper: str | None = Header(None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    logger.warning("ENTERED GOOGLE CALENDAR CONNECT ENDPOINT")
    logger.info(
        "GOOGLE_CALENDAR_CONNECT_REQUEST tenant_slug=%s tenant_id=%s x_tenant_slug=%s x_tenant_id=%s x_tenant_id_upper=%s",
        tenant_slug,
        tenant_id,
        x_tenant_slug,
        x_tenant_id,
        x_tenant_id_upper,
    )
    resolution = resolve_current_tenant(
        request,
        db=db,
        x_tenant_slug=x_tenant_slug or "",
        x_tenant_id=x_tenant_id or "",
        x_tenant_id_alt=x_tenant_id_upper or "",
        tenant_slug=tenant_slug or "",
        tenant_id=tenant_id or "",
    )
    logger.info(
        "GOOGLE_CALENDAR_TENANT_RESOLUTION_RESULT resolved=%s tenant_id=%s source=%s",
        bool(resolution),
        resolution.tenant.id if resolution else None,
        resolution.source if resolution else None,
    )
    if not resolution:
        raise HTTPException(status_code=400, detail="Tenant não identificado")

    tenant = resolution.tenant
    if not _client_id():
        raise HTTPException(status_code=500, detail="GOOGLE_CALENDAR_CLIENT_ID não configurado")
    state = create_oauth_state(tenant.id)
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/callback", name="google_calendar_callback")
def google_calendar_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    if error:
        raise HTTPException(status_code=400, detail="OAuth Google recusado")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Callback OAuth inválido")
    payload = verify_oauth_state(state)
    tenant_id = uuid.UUID(str(payload["tenant_id"]))
    token_payload = _exchange_code_for_tokens(code, _redirect_uri(request))
    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Access token ausente")
    account_email = _fetch_account_email(access_token)
    expires_at = None
    if token_payload.get("expires_in"):
        expires_at = datetime.utcnow() + timedelta(seconds=int(token_payload["expires_in"]))
    scopes = token_payload.get("scope", " ".join(SCOPES)).split()
    IntegrationConnectionService(db).upsert_connection(
        tenant_id=tenant_id,
        provider=PROVIDER,
        auth_type=AUTH_TYPE,
        access_token=access_token,
        refresh_token=token_payload.get("refresh_token"),
        expires_at=expires_at,
        scopes=scopes,
        metadata={"account_email": account_email} if account_email else {},
    )
    return {"provider": PROVIDER, "connected": True, "account_email": account_email}


@router.get("/status", response_model=IntegrationConnectionStatusOut)
def google_calendar_status(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.get_connection(tenant.id, PROVIDER), provider=PROVIDER)


@router.delete("/disconnect", response_model=IntegrationConnectionStatusOut)
def google_calendar_disconnect(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.disconnect_connection(tenant.id, PROVIDER), provider=PROVIDER)
