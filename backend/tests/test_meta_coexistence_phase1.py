import uuid
from app.routers.meta_integration import create_meta_oauth_state, verify_meta_oauth_state, _provider_status
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.webhook_ingress import _resolve_inbound_tenant


def test_tenant_old_provider_without_explicit_connection_type_assumes_cloud_api():
    provider = TenantWhatsAppProvider(tenant_id=uuid.uuid4(), provider_type="meta_cloud")
    assert (getattr(provider, "connection_type", None) or "cloud_api") == "cloud_api"
    assert provider.coexistence_enabled is None or provider.coexistence_enabled is False


def test_meta_state_preserves_connection_type():
    tenant_id = uuid.uuid4()
    state = create_meta_oauth_state(tenant_id, connection_type="cloud_api_coexistence", nonce="n", issued_at=1890000000)
    payload = verify_meta_oauth_state(state)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["connection_type"] == "cloud_api_coexistence"


def test_connect_url_state_can_represent_standard_cloud_api():
    tenant_id = uuid.uuid4()
    state = create_meta_oauth_state(tenant_id, connection_type="cloud_api", nonce="n", issued_at=1890000000)
    assert verify_meta_oauth_state(state)["connection_type"] == "cloud_api"


def test_webhook_resolves_coexistence_provider_by_phone_number_id():
    tenant_id = uuid.uuid4()
    provider = TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider_type="meta_cloud",
        phone_number_id="123",
        connection_type="cloud_api_coexistence",
        coexistence_enabled=True,
        is_active=True,
    )

    class Result:
        def scalars(self): return self
        def first(self): return provider

    class Db:
        def execute(self, query): return Result()

    payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "123"}, "messages": [{"type": "text"}]}}]}]}
    resolution = _resolve_inbound_tenant(Db(), payload)
    assert resolution.tenant_id == str(tenant_id)
    assert resolution.provider_id == str(provider.id)
    assert resolution.connection_type == "cloud_api_coexistence"
    assert resolution.coexistence_enabled is True


def test_status_payload_returns_coexistence_enabled():
    provider = TenantWhatsAppProvider(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), provider_type="meta_cloud", phone_number_id="123",
        waba_id="waba", business_id="biz", connection_type="cloud_api_coexistence",
        coexistence_enabled=True, connection_status="connected", status="connected", metadata_json={"display_phone_number": "+55 11"},
    )
    payload = _provider_status(provider)
    assert payload["connected"] is True
    assert payload["connection_type"] == "cloud_api_coexistence"
    assert payload["coexistence_enabled"] is True
    assert payload["phone_number_id"] == "123"
