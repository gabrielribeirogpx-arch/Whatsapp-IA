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
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import TenantResolution, get_current_tenant, get_current_tenant_resolution, resolve_current_tenant

PROVIDER = "gmail"
AUTH_TYPE = "oauth2"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
    "profile",
]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_TTL_SECONDS = 10 * 60

router = APIRouter(prefix="/integrations/gmail", tags=["gmail-integration"])
logger = logging.getLogger(__name__)


def _frontend_base_url() -> str:
    configured = (
        os.getenv("FRONTEND_URL")
        or "https://frontend-whatsapp-ia-production.up.railway.app"
    ).strip().rstrip("/")
    parsed = urlparse(configured)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.warning("GMAIL_INVALID_FRONTEND_URL value=%s", configured)
        return "https://frontend-whatsapp-ia-production.up.railway.app"
    return configured


def _frontend_oauth_result_url(status: str) -> str:
    base = _frontend_base_url()
    parsed = urlparse(f"{base}/dashboard/ai/mcp")
    query = urlencode({
        "integration": PROVIDER,
        "status": status,
    })
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def get_gmail_connect_tenant(
    resolution: TenantResolution | None = Depends(get_current_tenant_resolution),
) -> Tenant:
    if not resolution:
        raise HTTPException(status_code=400, detail="Tenant não identificado")
    logger.info(
        "event=gmail_connect_tenant_resolved tenant_id=%s source=%s",
        resolution.tenant.id,
        resolution.source,
    )
    return resolution.tenant


def _client_id() -> str:
    return (
        os.getenv("GMAIL_CLIENT_ID")
        or os.getenv("GOOGLE_CLIENT_ID")
        or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
        or ""
    ).strip()


def _client_secret() -> str:
    return (
        os.getenv("GMAIL_CLIENT_SECRET")
        or os.getenv("GOOGLE_CLIENT_SECRET")
        or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        or ""
    ).strip()


def _state_secret() -> bytes:
    secret = (
        os.getenv("GMAIL_STATE_SECRET")
        or os.getenv("AUTH_SECRET")
        or os.getenv("SECRET_KEY")
        or os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY")
        or ""
    ).strip()
    if not secret:
        raise HTTPException(status_code=500, detail="Segredo OAuth não configurado")
    return secret.encode("utf-8")


def _redirect_uri(request: Request) -> str:
    configured = (os.getenv("GMAIL_REDIRECT_URI") or "").strip()
    base_url = (os.getenv("BASE_URL") or "").strip().rstrip("/")
    redirect_uri = configured or (f"{base_url}/api/integrations/gmail/callback" if base_url else str(request.url_for("gmail_callback")))
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=500, detail="GMAIL_REDIRECT_URI inválida")
    logger.info(
        "GMAIL_REDIRECT_URI_RESOLVED %s",
        json.dumps({"redirect_uri": redirect_uri, "provider": PROVIDER}, separators=(",", ":"), sort_keys=True),
    )
    return redirect_uri


def _validate_gmail_connect_config(request: Request) -> None:
    if not _client_id():
        raise HTTPException(status_code=500, detail="GMAIL_CLIENT_ID não configurado")
    if not _client_secret():
        raise HTTPException(status_code=500, detail="GMAIL_CLIENT_SECRET não configurado")
    _state_secret()
    _redirect_uri(request)


def create_oauth_state(tenant_id: uuid.UUID, *, nonce: str | None = None, issued_at: int | None = None) -> str:
    payload = {
        "tenant_id": str(tenant_id),
        "provider": PROVIDER,
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
    if payload.get("provider") != PROVIDER:
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


@router.get("/connect-url")
@router.get("/connect")
def connect_gmail(
    request: Request,
    tenant_slug: str | None = Query(None),
    tenant_id: str | None = Query(None),
    x_tenant_slug: str | None = Header(None, alias="X-Tenant-Slug"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
    x_tenant_id_upper: str | None = Header(None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    try:
        logger.warning("ENTERED GMAIL CONNECT ENDPOINT")
        redirect_uri = _redirect_uri(request)
        callback_path = urlparse(redirect_uri).path
        frontend_return_url = _frontend_oauth_result_url("connected")
        logger.info(
            "GMAIL_OAUTH_CONNECT_URL_REQUESTED provider=%s redirect_uri=%s scopes=%s callback_path=%s frontend_return_url=%s tenant_slug=%s tenant_id=%s x_tenant_slug=%s x_tenant_id=%s x_tenant_id_upper=%s",
            PROVIDER,
            redirect_uri,
            SCOPES,
            callback_path,
            frontend_return_url,
            tenant_slug,
            tenant_id,
            x_tenant_slug,
            x_tenant_id,
            x_tenant_id_upper,
        )
        _validate_gmail_connect_config(request)
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
            "GMAIL_TENANT_RESOLUTION_RESULT resolved=%s tenant_id=%s source=%s",
            bool(resolution),
            resolution.tenant.id if resolution else None,
            resolution.source if resolution else None,
        )
        if not resolution:
            raise HTTPException(status_code=400, detail="Tenant não identificado")

        tenant = resolution.tenant
        if not getattr(tenant, "id", None):
            raise HTTPException(status_code=500, detail="Tenant sem ID")
        state = create_oauth_state(tenant.id)
        params = {
            "client_id": _client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        oauth_url = f"{AUTH_URL}?{urlencode(params)}"
        logger.info(
            "GMAIL_OAUTH_CONNECT_URL_GENERATED provider=%s redirect_uri=%s scopes=%s callback_path=%s frontend_return_url=%s",
            PROVIDER,
            redirect_uri,
            SCOPES,
            callback_path,
            frontend_return_url,
        )
        return RedirectResponse(oauth_url, status_code=302)
    except Exception as exc:
        logger.exception(
            "GMAIL_CONNECT_EXCEPTION exception_type=%s exception_message=%s",
            type(exc).__name__,
            str(exc),
        )
        raise


@router.get("/callback", name="gmail_callback")
def gmail_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    try:
        redirect_uri = _redirect_uri(request)
        callback_path = urlparse(str(request.url)).path
        frontend_return_url = _frontend_oauth_result_url("connected")
        logger.info(
            "GMAIL_OAUTH_CALLBACK_RECEIVED provider=%s redirect_uri=%s scopes=%s callback_path=%s frontend_return_url=%s has_code=%s has_state=%s error=%s integration=%s",
            PROVIDER,
            redirect_uri,
            SCOPES,
            callback_path,
            frontend_return_url,
            bool(code),
            bool(state),
            error,
            PROVIDER,
        )
        if error:
            raise HTTPException(status_code=400, detail="OAuth Google recusado")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Callback OAuth inválido")
        payload = verify_oauth_state(state)
        logger.info(
            "GMAIL_OAUTH_CALLBACK_STATE_DECODED provider=%s state_provider=%s tenant_id=%s redirect_uri=%s scopes=%s callback_path=%s frontend_return_url=%s integration=%s",
            PROVIDER,
            payload.get("provider"),
            payload.get("tenant_id"),
            redirect_uri,
            SCOPES,
            callback_path,
            frontend_return_url,
            PROVIDER,
        )
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
        token_payload = _exchange_code_for_tokens(code, redirect_uri)
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
        return RedirectResponse(_frontend_oauth_result_url("connected"), status_code=302)
    except Exception as exc:
        logger.exception(
            "GMAIL_CALLBACK_EXCEPTION exception_type=%s exception_message=%s",
            type(exc).__name__,
            str(exc),
        )
        return RedirectResponse(_frontend_oauth_result_url("error"), status_code=302)


@router.get("/status", response_model=IntegrationConnectionStatusOut)
def gmail_status(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.get_connection(tenant.id, PROVIDER), provider=PROVIDER)


@router.delete("/disconnect", response_model=IntegrationConnectionStatusOut)
def gmail_disconnect(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.disconnect_connection(tenant.id, PROVIDER), provider=PROVIDER)
