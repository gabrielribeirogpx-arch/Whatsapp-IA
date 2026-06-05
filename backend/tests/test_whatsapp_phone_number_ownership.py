from __future__ import annotations

import logging
import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest

from app.models.tenant import Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.tenant_service import resolve_tenant_by_phone_number_id
from app.services.whatsapp_provider_service import (
    DuplicatePhoneNumberProviderError,
    create_provider,
    list_providers,
    update_provider,
)


class _Payload(SimpleNamespace):
    def model_dump(self, exclude_unset: bool = False):
        return dict(self.__dict__)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDB:
    def __init__(self):
        self.tenants = []
        self.providers = []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, Tenant) and obj not in self.tenants:
            self.tenants.append(obj)
        if isinstance(obj, TenantWhatsAppProvider) and obj not in self.providers:
            self.providers.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None

    def refresh(self, _obj):
        return None

    def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        params = statement.compile().params
        if entity is TenantWhatsAppProvider:
            rows = self.providers
            if "phone_number_id_1" in params:
                rows = [
                    item
                    for item in rows
                    if item.phone_number_id == params["phone_number_id_1"]
                ]
            if "id_1" in params:
                if "phone_number_id_1" in params:
                    rows = [item for item in rows if item.id != params["id_1"]]
                else:
                    rows = [item for item in rows if item.id == params["id_1"]]
            if "tenant_id_1" in params:
                rows = [
                    item for item in rows if item.tenant_id == params["tenant_id_1"]
                ]
            return _Result(rows)
        if entity is Tenant:
            rows = self.tenants
            if "id_1" in params:
                rows = [item for item in rows if item.id == params["id_1"]]
            if "phone_number_id_1" in params:
                rows = [
                    item
                    for item in rows
                    if item.phone_number_id == params["phone_number_id_1"]
                ]
            return _Result(rows)
        return _Result([])


def _tenant(db: _FakeDB, *, name: str, slug: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name=name, slug=slug)
    db.add(tenant)
    return tenant


def test_provider_phone_number_id_must_be_exclusive_across_tenants():
    db = _FakeDB()
    owner = _tenant(db, name="Owner", slug="owner")
    other = _tenant(db, name="Other", slug="other")

    provider = create_provider(
        db,
        owner.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id=" 876969468828520 ",
            display_name="owner",
        ),
    )

    assert provider.phone_number_id == "876969468828520"
    with pytest.raises(DuplicatePhoneNumberProviderError):
        create_provider(
            db,
            other.id,
            _Payload(
                provider_type="meta_cloud",
                phone_number_id="876969468828520",
                display_name="duplicate",
            ),
        )


def test_meta_provider_create_succeeds_after_hidden_provider_phone_release():
    db = _FakeDB()
    hidden_tenant_id = uuid.UUID("b0c1a7d5-587b-476f-89d1-5596c02dad5d")
    new_owner = _tenant(db, name="New Owner", slug="new-owner")
    hidden_provider = TenantWhatsAppProvider(
        id=uuid.UUID("bb2848cc-782f-4f59-a2b7-8860d3c9bc61"),
        tenant_id=hidden_tenant_id,
        provider_type="meta_cloud",
        phone_number_id=None,
        is_active=False,
        status="disconnected",
        metadata_json={
            "previous_phone_number_id": "876969468828520",
            "hidden_provider": True,
            "remediation": "20260601_release_hidden_phone",
        },
    )
    db.add(hidden_provider)

    provider = create_provider(
        db,
        new_owner.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id="876969468828520",
            display_name="Meta definitivo",
        ),
    )

    assert provider.phone_number_id == "876969468828520"
    assert provider.tenant_id == new_owner.id
    assert hidden_provider.phone_number_id is None


def test_duplicate_protection_still_blocks_non_released_phone_numbers():
    db = _FakeDB()
    owner = _tenant(db, name="Owner", slug="owner")
    other = _tenant(db, name="Other", slug="other")
    create_provider(
        db,
        owner.id,
        _Payload(provider_type="meta_cloud", phone_number_id="555000111222"),
    )

    with pytest.raises(DuplicatePhoneNumberProviderError):
        create_provider(
            db,
            other.id,
            _Payload(provider_type="meta_cloud", phone_number_id="555000111222"),
        )


def test_provider_create_conflict_returns_diagnostic_payload_and_log(caplog):
    db = _FakeDB()
    owner = _tenant(db, name="Owner", slug="owner")
    other = _tenant(db, name="Other", slug="other")
    provider = create_provider(
        db,
        owner.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id="876969468828520",
            display_name="owner",
        ),
    )
    provider.metadata_json = {"remediation": "20260530_whatsapp_phone_owner"}

    caplog.set_level(logging.WARNING, logger="app.services.whatsapp_provider_service")
    with pytest.raises(DuplicatePhoneNumberProviderError) as exc_info:
        create_provider(
            db,
            other.id,
            _Payload(
                provider_type="meta_cloud",
                phone_number_id="876969468828520",
                display_name="duplicate",
            ),
        )

    payload = exc_info.value.to_dict()
    assert payload["provider_id"] == str(provider.id)
    assert payload["tenant_id"] == str(owner.id)
    assert payload["phone_number_id"] == "876969468828520"
    assert (
        payload["validation"]
        == "whatsapp_provider_service._assert_phone_number_id_available"
    )
    assert payload["hidden_provider"] is True
    assert payload["soft_delete"] is False
    assert payload["ownership_migration"] == "20260530_whatsapp_phone_owner"
    assert payload["blocking_provider"]["provider_id"] == str(provider.id)
    assert "tenant_whatsapp_providers.id" in payload["reason"]
    assert "[PROVIDER CREATE CONFLICT]" in caplog.text
    assert f"provider_id={provider.id}" in caplog.text
    assert "phone_number_id=876969468828520" in caplog.text


def test_provider_update_cannot_steal_phone_number_id_from_other_tenant():
    db = _FakeDB()
    owner = _tenant(db, name="Owner", slug="owner")
    other = _tenant(db, name="Other", slug="other")
    create_provider(
        db,
        owner.id,
        _Payload(provider_type="meta_cloud", phone_number_id="876969468828520"),
    )
    other_provider = create_provider(
        db, other.id, _Payload(provider_type="meta_cloud", phone_number_id="999")
    )

    with pytest.raises(DuplicatePhoneNumberProviderError):
        update_provider(
            db, other.id, other_provider.id, _Payload(phone_number_id="876969468828520")
        )


def test_tenant_resolution_prefers_provider_owner_over_legacy_tenant_phone():
    db = _FakeDB()
    owner = _tenant(db, name="Owner", slug="owner")
    legacy = _tenant(db, name="Legacy", slug="legacy")
    legacy.phone_number_id = "876969468828520"
    create_provider(
        db,
        owner.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id="876969468828520",
            is_active=True,
            status="connected",
        ),
    )

    resolved = resolve_tenant_by_phone_number_id(db, "876969468828520")

    assert resolved.id == owner.id


def test_provider_list_logs_query_result_and_returns_active_provider(caplog):
    db = _FakeDB()
    tenant = _tenant(db, name="Owner", slug="owner")
    provider = create_provider(
        db,
        tenant.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id="876969468828520",
            display_name="Meta Cloud",
            is_active=True,
            status="active",
        ),
    )

    caplog.set_level(logging.INFO, logger="app.services.whatsapp_provider_service")
    providers = list_providers(db, tenant.id)

    assert [item.id for item in providers] == [provider.id]
    assert providers[0].tenant_id == tenant.id
    assert providers[0].is_active is True
    assert "[WHATSAPP PROVIDERS LIST QUERY]" in caplog.text
    assert "[WHATSAPP PROVIDERS LIST RESULT]" in caplog.text
    assert f"provider_ids=['{provider.id}']" in caplog.text
    assert "provider_type" in caplog.text
    assert "deleted_at" in caplog.text


def test_provider_list_returns_persisted_provider_without_meta_lookup(monkeypatch):
    db = _FakeDB()
    tenant = _tenant(db, name="Owner", slug="owner")
    provider = create_provider(
        db,
        tenant.id,
        _Payload(
            provider_type="meta_cloud",
            phone_number_id="876969468828520",
            display_name="Meta Cloud",
            is_active=True,
            status="connected",
            connection_status="token_expired",
            last_validation_error="Token da Meta expirado.",
        ),
    )

    def _fail_meta_lookup(*_args, **_kwargs):
        raise AssertionError("GET /api/whatsapp/providers não deve consultar Meta Cloud API")

    monkeypatch.setattr(
        "app.services.whatsapp_provider_service.MetaCloudClient",
        _fail_meta_lookup,
    )

    providers = list_providers(db, tenant.id)

    assert [item.id for item in providers] == [provider.id]
    assert providers[0].connection_status == "token_expired"
    assert providers[0].last_validation_error == "Token da Meta expirado."


def test_meta_401_validation_marks_token_expired_without_deleting_provider(monkeypatch):
    from app.integrations.meta.meta_cloud_client import MetaApiError
    from app.services import whatsapp_provider_service

    db = _FakeDB()
    tenant = _tenant(db, name="Owner", slug="owner")
    provider = TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        provider_type="meta_cloud",
        display_name="Meta Cloud",
        waba_id="waba-1",
        business_id="business-1",
        phone_number_id="phone-1",
        access_token_encrypted="encrypted-token",
        is_active=True,
        status="connected",
        connection_status="connected",
        metadata_json={},
    )
    db.add(provider)

    async def _expired(*_args, **_kwargs):
        raise MetaApiError("Token da Meta expirado.", status_code=401)

    monkeypatch.setenv("WHATSAPP_SECRET_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(whatsapp_provider_service, "decrypt_secret", lambda _value: "plain-token")
    monkeypatch.setattr(whatsapp_provider_service, "_sync_meta_provider_metadata", _expired)

    result = whatsapp_provider_service.test_provider_connection(db, tenant.id, provider.id)

    assert result["ok"] is False
    assert result["status"] == "token_expired"
    assert provider in db.providers
    assert provider.connection_status == "token_expired"
    assert provider.status == "token_expired"
    assert provider.last_validation_at is not None
    assert provider.last_validation_error == "Token da Meta expirado."
    assert list_providers(db, tenant.id)[0].id == provider.id


def test_meta_phone_validation_error_marks_invalid_phone_without_hiding_provider(monkeypatch):
    from app.integrations.meta.meta_cloud_client import MetaApiError
    from app.services import whatsapp_provider_service

    db = _FakeDB()
    tenant = _tenant(db, name="Owner", slug="owner")
    provider = TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        provider_type="meta_cloud",
        display_name="Meta Cloud",
        waba_id="waba-1",
        business_id="business-1",
        phone_number_id="bad-phone",
        access_token_encrypted="encrypted-token",
        is_active=True,
        status="connected",
        connection_status="connected",
        metadata_json={},
    )
    db.add(provider)

    async def _bad_phone(*_args, **_kwargs):
        raise MetaApiError("phone_number_id inválido na configuração.", status_code=400)

    monkeypatch.setenv("WHATSAPP_SECRET_ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(whatsapp_provider_service, "decrypt_secret", lambda _value: "plain-token")
    monkeypatch.setattr(whatsapp_provider_service, "_sync_meta_provider_metadata", _bad_phone)

    result = whatsapp_provider_service.test_provider_connection(db, tenant.id, provider.id)

    assert result["status"] == "invalid_phone_number"
    assert provider.connection_status == "invalid_phone_number"
    assert list_providers(db, tenant.id)[0].id == provider.id
