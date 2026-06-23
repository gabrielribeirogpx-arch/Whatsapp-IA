from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any, Literal
from urllib.parse import urlencode

import requests

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
STATE_TTL_SECONDS = 10 * 60
_META_NONCES: dict[str, int] = {}
GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v20.0")
GRAPH_BASE_URL = os.getenv(
    "META_GRAPH_BASE_URL", f"https://graph.facebook.com/{GRAPH_API_VERSION}"
).rstrip("/")
META_EMBEDDED_SIGNUP_REQUIRED_SCOPES = (
    "whatsapp_business_management",
    "whatsapp_business_messaging",
)
META_EMBEDDED_SIGNUP_CONFIG_URL = (
    "https://developers.facebook.com/apps/{app_id}/whatsapp-business/wa-settings/"
    "?business_id={business_id}"
)


def _state_secret() -> bytes:
    return (
        os.getenv("OAUTH_STATE_SECRET")
        or os.getenv("SECRET_KEY")
        or os.getenv("WHATSAPP_SECRET_ENCRYPTION_KEY")
        or "dev-state-secret"
    ).encode()


def _normalize_connection_type(value: object) -> ConnectionType:
    candidate = str(value or "cloud_api").strip()
    if candidate not in VALID_CONNECTION_TYPES:
        raise HTTPException(status_code=400, detail="connection_type inválido")
    return candidate  # type: ignore[return-value]


def _prune_nonces(now: int | None = None) -> None:
    current = now or int(time.time())
    for nonce, expires_at in list(_META_NONCES.items()):
        if expires_at <= current:
            _META_NONCES.pop(nonce, None)


def _persist_nonce(nonce: str, issued_at: int) -> None:
    _prune_nonces(issued_at)
    _META_NONCES[nonce] = issued_at + STATE_TTL_SECONDS


def create_meta_oauth_state(
    tenant_id: object,
    *,
    connection_type: ConnectionType = "cloud_api",
    nonce: str | None = None,
    issued_at: int | None = None,
    persist_nonce: bool = True,
) -> str:
    issued = issued_at or int(time.time())
    state_nonce = nonce or secrets.token_urlsafe(24)
    payload = {
        "tenant_id": str(tenant_id),
        "provider": "meta",
        "connection_type": connection_type,
        "nonce": state_nonce,
        "iat": issued,
    }
    payload_b64 = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )
    sig_b64 = (
        base64.urlsafe_b64encode(
            hmac.new(_state_secret(), payload_b64.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    if persist_nonce:
        _persist_nonce(state_nonce, issued)
    return f"{payload_b64}.{sig_b64}"


def verify_meta_oauth_state(
    state: str, *, consume_nonce: bool = False
) -> dict[str, Any]:
    try:
        payload_b64, sig_b64 = state.split(".", 1)
        expected = hmac.new(
            _state_secret(), payload_b64.encode(), hashlib.sha256
        ).digest()
        actual = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("bad signature")
        payload = json.loads(
            base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="State Meta inválido") from exc
    now = int(time.time())
    issued_at = int(payload.get("iat", 0))
    if now - issued_at > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="State Meta expirado")
    if payload.get("provider") != "meta" or not payload.get("tenant_id"):
        raise HTTPException(status_code=400, detail="State Meta inválido")
    payload["connection_type"] = _normalize_connection_type(
        payload.get("connection_type")
    )
    if consume_nonce:
        _prune_nonces(now)
        nonce = str(payload.get("nonce") or "")
        expires_at = _META_NONCES.pop(nonce, None)
        if not expires_at or expires_at <= now:
            raise HTTPException(
                status_code=400, detail="Nonce Meta inválido ou reutilizado"
            )
    return payload


def _redirect_uri() -> str:
    return (
        os.getenv("META_REDIRECT_URI")
        or os.getenv("BACKEND_PUBLIC_URL", "").rstrip("/")
        + "/api/integrations/meta/callback"
    )


def _embedded_signup_scopes() -> str:
    configured = os.getenv("META_EMBEDDED_SIGNUP_SCOPES")
    requested = [
        scope.strip()
        for scope in (
            configured.split(",")
            if configured
            else META_EMBEDDED_SIGNUP_REQUIRED_SCOPES
        )
        if scope.strip()
    ]
    allowed = set(META_EMBEDDED_SIGNUP_REQUIRED_SCOPES)
    scopes = [scope for scope in requested if scope in allowed]
    if not scopes:
        scopes = list(META_EMBEDDED_SIGNUP_REQUIRED_SCOPES)
    return ",".join(dict.fromkeys(scopes))


def _connect_url(state: str) -> str:
    base_url = os.getenv(
        "META_EMBEDDED_SIGNUP_URL", "https://www.facebook.com/dialog/oauth"
    )
    config_id = (
        os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID")
        or os.getenv("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID")
        or ""
    )
    if not config_id:
        app_id = os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID") or "<META_APP_ID>"
        business_id = os.getenv("META_BUSINESS_ID") or os.getenv("FACEBOOK_BUSINESS_ID") or "<BUSINESS_ID>"
        logger.warning(
            "META_EMBEDDED_SIGNUP_CONFIG_ID_MISSING "
            "config_id_required=true "
            "set_env=META_EMBEDDED_SIGNUP_CONFIG_ID "
            "fallback_env=WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID "
            "configuration_url=%s",
            META_EMBEDDED_SIGNUP_CONFIG_URL.format(
                app_id=app_id, business_id=business_id
            ),
        )
    params = {
        "client_id": os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID") or "",
        "redirect_uri": _redirect_uri(),
        "state": state,
        "scope": _embedded_signup_scopes(),
        "response_type": "code",
        "config_id": config_id,
        "extras": json.dumps(
            {
                "feature": "whatsapp_embedded_signup",
                "setup": {"solution": "coexistence"},
            }
        ),
    }
    return f"{base_url}?{urlencode({k: v for k, v in params.items() if v})}"


def _provider_status(provider: TenantWhatsAppProvider | None) -> dict[str, Any]:
    meta = (provider.metadata_json or {}) if provider else {}
    return {
        "connected": bool(provider and provider.connection_status == "connected"),
        "provider_id": str(provider.id) if provider else None,
        "phone_number_id": provider.phone_number_id if provider else None,
        "display_phone_number": (
            (provider.phone_display_name or meta.get("display_phone_number"))
            if provider
            else None
        ),
        "waba_id": provider.waba_id if provider else None,
        "business_id": provider.business_id if provider else None,
        "business_manager_id": getattr(provider, "business_manager_id", None)
        or (provider.business_id if provider else None),
        "connection_type": (
            getattr(provider, "connection_type", None) or "cloud_api"
            if provider
            else "cloud_api"
        ),
        "coexistence_enabled": (
            bool(getattr(provider, "coexistence_enabled", False)) if provider else False
        ),
        "coexistence_status": (
            getattr(provider, "coexistence_status", None) if provider else None
        ),
        "status": provider.connection_status if provider else "disconnected",
        "account": meta.get("meta_token_subject_name")
        or meta.get("business_name")
        or meta.get("waba_name"),
        "name": provider.display_name if provider else None,
        "display_name": (
            provider.phone_display_name or provider.display_name if provider else None
        ),
        "verified_name": (
            provider.phone_verified_name or meta.get("verified_name")
            if provider
            else None
        ),
        "phone_number": (
            provider.business_phone_number_id
            or provider.phone_display_name
            or meta.get("display_phone_number")
            if provider
            else None
        ),
    }


@router.get("/status")
def get_meta_status(
    db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)
):
    provider = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == tenant.id,
                TenantWhatsAppProvider.provider_type == "meta_cloud",
            )
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    return _provider_status(provider)


@router.api_route("/connect-url", methods=["GET", "POST"])
async def get_meta_connect_url(
    request: Request,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    connection_type: str | None = Query(default=None),
):
    body: dict[str, Any] = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    normalized = _normalize_connection_type(
        body.get("connection_type") or connection_type
    )
    logger.info(
        "META_CONNECT_URL_REQUESTED tenant_id=%s connection_type=%s",
        tenant.id,
        normalized,
    )
    state = create_meta_oauth_state(tenant.id, connection_type=normalized)
    url = _connect_url(state)
    logger.info(
        "META_COEX_CONNECT_URL_CREATED tenant_id=%s connection_type=%s state_present=%s",
        tenant.id,
        normalized,
        bool(state),
    )
    return {"url": url, "state": state, "connection_type": normalized}


def _meta_get(
    path: str, token: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = requests.get(
        f"{GRAPH_BASE_URL}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=20,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Falha ao consultar Meta Graph API")
    return response.json()


def _exchange_code_for_token(code: str, redirect_uri: str) -> str:
    response = requests.get(
        f"{GRAPH_BASE_URL}/oauth/access_token",
        params={
            "client_id": os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID"),
            "client_secret": os.getenv("META_APP_SECRET")
            or os.getenv("FACEBOOK_APP_SECRET"),
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=400, detail="Falha ao trocar code Meta por token"
        )
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(status_code=400, detail="Token Meta ausente")
    logger.info("META_COEX_TOKEN_EXCHANGED")
    return token


def _first(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def _discover_meta_business(token: str) -> dict[str, Any]:
    businesses = _meta_get("me/businesses", token, {"fields": "id,name"}).get(
        "data", []
    )
    business = _first(businesses) or {}
    business_id = business.get("id")
    logger.info("META_COEX_BUSINESS_DISCOVERED business_found=%s", bool(business_id))
    wabas: list[dict[str, Any]] = []
    if business_id:
        for edge in (
            "owned_whatsapp_business_accounts",
            "client_whatsapp_business_accounts",
        ):
            wabas.extend(
                _meta_get(f"{business_id}/{edge}", token, {"fields": "id,name"}).get(
                    "data", []
                )
            )
    if not wabas:
        wabas = _meta_get(
            "me/whatsapp_business_accounts", token, {"fields": "id,name"}
        ).get("data", [])
    waba = _first(wabas) or {}
    waba_id = waba.get("id")
    if not waba_id:
        raise HTTPException(
            status_code=400, detail="Nenhuma WABA encontrada para a conta Meta"
        )
    phones = _meta_get(
        f"{waba_id}/phone_numbers",
        token,
        {
            "fields": "id,display_phone_number,verified_name,quality_rating,name_status,code_verification_status,platform_type"
        },
    ).get("data", [])
    phone = _first(phones) or {}
    phone_id = phone.get("id")
    if not phone_id:
        raise HTTPException(
            status_code=400, detail="Nenhum número WhatsApp encontrado na WABA"
        )
    logger.info("META_COEX_PHONE_DISCOVERED phone_found=True")
    return {
        "business_id": business_id,
        "business_name": business.get("name"),
        "waba_id": waba_id,
        "waba_name": waba.get("name"),
        "phone": phone,
    }


@router.get("/callback")
def meta_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    logger.info(
        "META_COEX_CALLBACK_RECEIVED has_code=%s has_state=%s", bool(code), bool(state)
    )
    payload = verify_meta_oauth_state(state or "", consume_nonce=True)
    logger.info("META_COEX_STATE_VALIDATED")
    connection_type = _normalize_connection_type(payload.get("connection_type"))
    tenant_id = uuid.UUID(str(payload["tenant_id"]))
    if not code:
        raise HTTPException(status_code=400, detail="Code Meta ausente")
    token = _exchange_code_for_token(code, _redirect_uri())
    discovered = _discover_meta_business(token)
    phone = discovered["phone"]
    phone_number_id = phone["id"]
    existing = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == tenant_id,
                TenantWhatsAppProvider.provider_type == "meta_cloud",
            )
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    provider = existing or TenantWhatsAppProvider(
        tenant_id=tenant_id, provider_type="meta_cloud"
    )
    provider.display_name = discovered.get("waba_name") or "Meta WhatsApp Coexistence"
    provider.waba_id = discovered["waba_id"]
    provider.phone_number_id = phone_number_id
    provider.business_phone_number_id = (
        phone.get("display_phone_number") or phone_number_id
    )
    provider.business_id = discovered.get("business_id")
    if hasattr(provider, "business_manager_id"):
        provider.business_manager_id = discovered.get("business_id")
    provider.phone_display_name = phone.get("display_phone_number")
    provider.phone_verified_name = phone.get("verified_name")
    provider.access_token_encrypted = encrypt_secret(token)
    provider.connection_type = (
        "cloud_api_coexistence"
        if connection_type == "cloud_api_coexistence"
        else connection_type
    )
    provider.coexistence_enabled = provider.connection_type == "cloud_api_coexistence"
    provider.coexistence_status = "active" if provider.coexistence_enabled else None
    provider.onboarding_metadata = {
        "provider": "meta",
        "embedded_signup": True,
        "business_id": discovered.get("business_id"),
    }
    provider.metadata_json = {
        "onboarding_source": "meta_embedded_signup",
        "business_name": discovered.get("business_name"),
        "waba_name": discovered.get("waba_name"),
        "display_phone_number": phone.get("display_phone_number"),
        "verified_name": phone.get("verified_name"),
        "quality_rating": phone.get("quality_rating"),
        "name_status": phone.get("name_status"),
        "code_verification_status": phone.get("code_verification_status"),
        "platform_type": phone.get("platform_type"),
    }
    provider.status = "connected"
    provider.connection_status = "connected"
    provider.is_active = True
    (
        db.execute(
            update(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == tenant_id,
                TenantWhatsAppProvider.id != provider.id,
            )
            .values(is_active=False)
        )
        if existing
        else db.execute(
            update(TenantWhatsAppProvider)
            .where(TenantWhatsAppProvider.tenant_id == tenant_id)
            .values(is_active=False)
        )
    )
    if not existing:
        db.add(provider)
    db.commit()
    (
        logger.info(
            "META_COEX_CONNECTION_UPDATED tenant_id=%s provider_id=%s",
            tenant_id,
            provider.id,
        )
        if existing
        else logger.info(
            "META_COEX_CONNECTION_CREATED tenant_id=%s provider_id=%s",
            tenant_id,
            provider.id,
        )
    )
    frontend = os.getenv("FRONTEND_URL", "").rstrip("/")
    if frontend:
        return RedirectResponse(
            f"{frontend}/dashboard/settings?tab=whatsapp-business&meta=connected"
        )
    return {
        "ok": True,
        "provider_id": str(provider.id),
        "connection_type": provider.connection_type,
        "coexistence_enabled": provider.coexistence_enabled,
    }


@router.post("/disconnect")
def disconnect_meta(
    db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)
):
    provider = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == tenant.id,
                TenantWhatsAppProvider.provider_type == "meta_cloud",
            )
            .order_by(
                TenantWhatsAppProvider.is_active.desc(),
                TenantWhatsAppProvider.updated_at.desc(),
            )
        )
        .scalars()
        .first()
    )
    if provider:
        provider.is_active = False
        provider.connection_status = "disconnected"
        provider.status = "disconnected"
        db.commit()
    return {"ok": True}
