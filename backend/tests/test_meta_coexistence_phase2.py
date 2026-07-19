import uuid

import pytest
from fastapi import HTTPException

from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.routers import meta_integration as meta


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Scalars:
    def __init__(self, item):
        self.item = item

    def first(self):
        return self.item


class _Result:
    def __init__(self, item):
        self.item = item

    def scalars(self):
        return _Scalars(self.item)


class _Db:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = None
        self.committed = False
        self.executed = []

    def execute(self, query):
        self.executed.append(query)
        return _Result(self.existing)

    def add(self, provider):
        self.added = provider

    def commit(self):
        self.committed = True


def test_state_generation_persists_nonce_and_validates(monkeypatch):
    meta._META_NONCES.clear()
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    tenant_id = uuid.uuid4()
    state = meta.create_meta_oauth_state(
        tenant_id, connection_type="cloud_api_coexistence", nonce="unique-nonce"
    )
    assert "unique-nonce" in meta._META_NONCES
    payload = meta.verify_meta_oauth_state(state, consume_nonce=True)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["connection_type"] == "cloud_api_coexistence"


def test_state_expiration(monkeypatch):
    meta._META_NONCES.clear()
    state = meta.create_meta_oauth_state(
        uuid.uuid4(),
        connection_type="cloud_api_coexistence",
        nonce="old",
        issued_at=1000,
    )
    monkeypatch.setattr(meta.time, "time", lambda: 1000 + meta.STATE_TTL_SECONDS + 1)
    with pytest.raises(HTTPException) as exc:
        meta.verify_meta_oauth_state(state, consume_nonce=True)
    assert exc.value.status_code == 400


def test_nonce_reuse_is_rejected(monkeypatch):
    meta._META_NONCES.clear()
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    state = meta.create_meta_oauth_state(
        uuid.uuid4(), connection_type="cloud_api_coexistence", nonce="single-use"
    )
    meta.verify_meta_oauth_state(state, consume_nonce=True)
    with pytest.raises(HTTPException) as exc:
        meta.verify_meta_oauth_state(state, consume_nonce=True)
    assert exc.value.status_code == 400


def test_invalid_state_signature_rejected(monkeypatch):
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    state = meta.create_meta_oauth_state(
        uuid.uuid4(), connection_type="cloud_api_coexistence"
    )
    with pytest.raises(HTTPException):
        meta.verify_meta_oauth_state(state + "tampered")


def test_token_exchange(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return _Response({"access_token": "token-from-meta"})

    monkeypatch.setattr(meta.requests, "get", fake_get)
    token = meta._exchange_code_for_token(
        "oauth-code", "https://api.example.com/api/integrations/meta/callback"
    )
    assert token == "token-from-meta"
    assert captured["params"]["code"] == "oauth-code"


def test_business_and_phone_discovery(monkeypatch):
    def fake_meta_get(path, token, params=None):
        if path == "me/businesses":
            return {"data": [{"id": "bm-1", "name": "Business"}]}
        if path == "bm-1/owned_whatsapp_business_accounts":
            return {"data": [{"id": "waba-1", "name": "WABA"}]}
        if path == "bm-1/client_whatsapp_business_accounts":
            return {"data": []}
        if path == "waba-1/phone_numbers":
            return {
                "data": [
                    {
                        "id": "phone-1",
                        "display_phone_number": "+55 11",
                        "verified_name": "Loja",
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(meta, "_meta_get", fake_meta_get)
    discovered = meta._discover_meta_business("token")
    assert discovered["business_id"] == "bm-1"
    assert discovered["waba_id"] == "waba-1"
    assert discovered["phone"]["id"] == "phone-1"


def test_callback_creates_provider(monkeypatch):
    tenant_id = uuid.uuid4()
    meta._META_NONCES.clear()
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    state = meta.create_meta_oauth_state(
        tenant_id, connection_type="cloud_api_coexistence", nonce="create"
    )
    monkeypatch.setattr(
        meta, "_exchange_code_for_token", lambda code, redirect_uri: "token"
    )
    monkeypatch.setattr(
        meta,
        "_discover_meta_business",
        lambda token: {
            "business_id": "bm-1",
            "business_name": "Biz",
            "waba_id": "waba-1",
            "waba_name": "WABA",
            "phone": {
                "id": "phone-1",
                "display_phone_number": "+55 11",
                "verified_name": "Loja",
            },
        },
    )
    monkeypatch.setattr(meta, "encrypt_secret", lambda value: f"encrypted:{value}")
    db = _Db()
    request = type(
        "Request",
        (),
        {
            "url": "https://api.example.com/api/integrations/meta/callback?code=x&state=y"
        },
    )()
    result = meta.meta_callback(request, code="code", state=state, db=db)
    assert result["ok"] is True
    assert db.added.phone_number_id == "phone-1"
    assert db.added.coexistence_status == "active"
    assert db.committed is True


def test_callback_updates_existing_provider(monkeypatch):
    tenant_id = uuid.uuid4()
    existing = TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider_type="meta_cloud",
        auth_type="embedded_signup",
        phone_number_id="old",
    )
    meta._META_NONCES.clear()
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    state = meta.create_meta_oauth_state(
        tenant_id, connection_type="cloud_api_coexistence", nonce="update"
    )
    monkeypatch.setattr(
        meta, "_exchange_code_for_token", lambda code, redirect_uri: "token"
    )
    monkeypatch.setattr(
        meta,
        "_discover_meta_business",
        lambda token: {
            "business_id": "bm-2",
            "business_name": "Biz",
            "waba_id": "waba-2",
            "waba_name": "WABA 2",
            "phone": {
                "id": "phone-2",
                "display_phone_number": "+55 22",
                "verified_name": "Loja 2",
            },
        },
    )
    monkeypatch.setattr(meta, "encrypt_secret", lambda value: f"encrypted:{value}")
    db = _Db(existing=existing)
    request = type(
        "Request", (), {"url": "https://api.example.com/api/integrations/meta/callback"}
    )()
    meta.meta_callback(request, code="code", state=state, db=db)
    assert db.added is None
    assert existing.phone_number_id == "phone-2"
    assert existing.waba_id == "waba-2"
    assert existing.coexistence_enabled is True


def test_callback_does_not_replace_manual_provider(monkeypatch):
    tenant_id = uuid.uuid4()
    manual = TenantWhatsAppProvider(
        id=uuid.uuid4(), tenant_id=tenant_id, provider_type="meta_cloud",
        auth_type="manual", phone_number_id="manual-phone", access_token_encrypted="manual-token",
    )
    meta._META_NONCES.clear()
    monkeypatch.setattr(meta.time, "time", lambda: 1890000000)
    state = meta.create_meta_oauth_state(tenant_id, nonce="manual-preserved")
    monkeypatch.setattr(meta, "_exchange_code_for_token", lambda *_: "token")
    monkeypatch.setattr(meta, "_discover_meta_business", lambda _: {
        "business_id": "bm", "business_name": "Biz", "waba_id": "waba",
        "waba_name": "WABA", "phone": {"id": "embedded-phone"},
    })
    monkeypatch.setattr(meta, "encrypt_secret", lambda value: f"encrypted:{value}")
    db = _Db(existing=manual)
    meta.meta_callback(type("Request", (), {"url": "https://api.example.com"})(), code="code", state=state, db=db)
    assert manual.phone_number_id == "manual-phone"
    assert manual.auth_type == "manual"
    assert db.added is not None
    assert db.added.auth_type == "embedded_signup"


def test_status_api_payload_includes_phase2_fields():
    provider = TenantWhatsAppProvider(
        tenant_id=uuid.uuid4(),
        provider_type="meta_cloud",
        connection_status="connected",
        connection_type="cloud_api_coexistence",
        coexistence_enabled=True,
        coexistence_status="active",
        waba_id="waba",
        business_id="bm",
        business_manager_id="bm",
        phone_number_id="pnid",
        business_phone_number_id="+55 11",
        phone_display_name="+55 11",
        phone_verified_name="Loja",
    )
    payload = meta._provider_status(provider)
    assert payload["connected"] is True
    assert payload["business_manager_id"] == "bm"
    assert payload["phone_number"] == "+55 11"
    assert payload["verified_name"] == "Loja"


def test_connect_url_uses_only_whatsapp_embedded_signup_scopes(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setenv("META_APP_ID", "app-123")
    monkeypatch.setenv(
        "META_REDIRECT_URI", "https://api.example.com/api/integrations/meta/callback"
    )
    monkeypatch.setenv("META_EMBEDDED_SIGNUP_CONFIG_ID", "config-123")
    monkeypatch.setenv(
        "META_EMBEDDED_SIGNUP_SCOPES",
        "whatsapp_business_management,whatsapp_business_messaging,business_management",
    )

    url = meta._connect_url("state-123")
    params = parse_qs(urlparse(url).query)

    assert params["scope"] == [
        "whatsapp_business_management,whatsapp_business_messaging"
    ]
    assert "business_management" not in params["scope"][0]
    assert params["config_id"] == ["config-123"]
    assert params["response_type"] == ["code"]
    assert '"feature": "whatsapp_embedded_signup"' in params["extras"][0]
    assert '"solution": "coexistence"' in params["extras"][0]


def test_connect_url_defaults_to_official_whatsapp_embedded_signup_scopes(monkeypatch):
    monkeypatch.delenv("META_EMBEDDED_SIGNUP_SCOPES", raising=False)
    assert (
        meta._embedded_signup_scopes()
        == "whatsapp_business_management,whatsapp_business_messaging"
    )
