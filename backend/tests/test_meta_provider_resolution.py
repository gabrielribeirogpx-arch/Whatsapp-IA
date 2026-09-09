from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services import whatsapp_message_service


class _Scalars:
    def __init__(self, providers):
        self._providers = providers

    def all(self):
        return self._providers


class _Result:
    def __init__(self, providers):
        self._providers = providers

    def scalars(self):
        return _Scalars(self._providers)


class _Db:
    def __init__(self, providers):
        self._providers = providers

    def execute(self, _query):
        return _Result(self._providers)


def _provider(*, tenant_id, updated_at, active=True):
    return TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider_type="meta_cloud",
        display_name="Meta",
        phone_number_id=str(uuid.uuid4()),
        access_token_encrypted="encrypted-token",
        is_active=active,
        status="connected",
        connection_status="connected",
        updated_at=updated_at,
    )


def test_resolution_uses_requested_active_provider_instead_of_first_active(monkeypatch):
    tenant_id = uuid.uuid4()
    now = datetime.utcnow()
    first = _provider(tenant_id=tenant_id, updated_at=now)
    requested = _provider(tenant_id=tenant_id, updated_at=now - timedelta(days=1))
    monkeypatch.setattr(whatsapp_message_service, "decrypt_secret", lambda value: value)

    credentials = whatsapp_message_service.resolve_active_meta_provider_credentials(
        _Db([first, requested]),
        tenant_id=str(tenant_id),
        provider_id=str(requested.id),
    )

    assert credentials is not None
    assert credentials["provider_id"] == str(requested.id)
    assert credentials["phone_number_id"] == requested.phone_number_id


def test_resolution_does_not_fall_back_when_requested_provider_is_inactive(monkeypatch):
    tenant_id = uuid.uuid4()
    now = datetime.utcnow()
    active = _provider(tenant_id=tenant_id, updated_at=now)
    requested = _provider(
        tenant_id=tenant_id, updated_at=now - timedelta(days=1), active=False
    )
    monkeypatch.setattr(whatsapp_message_service, "decrypt_secret", lambda value: value)

    credentials = whatsapp_message_service.resolve_active_meta_provider_credentials(
        _Db([active, requested]),
        tenant_id=str(tenant_id),
        provider_id=str(requested.id),
    )

    assert credentials is None


def test_resolution_keeps_current_order_when_payload_has_no_provider(monkeypatch):
    tenant_id = uuid.uuid4()
    now = datetime.utcnow()
    first = _provider(tenant_id=tenant_id, updated_at=now)
    second = _provider(tenant_id=tenant_id, updated_at=now - timedelta(days=1))
    monkeypatch.setattr(whatsapp_message_service, "decrypt_secret", lambda value: value)

    credentials = whatsapp_message_service.resolve_active_meta_provider_credentials(
        _Db([first, second]), tenant_id=str(tenant_id)
    )

    assert credentials is not None
    assert credentials["provider_id"] == str(first.id)
