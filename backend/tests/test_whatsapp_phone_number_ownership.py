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
