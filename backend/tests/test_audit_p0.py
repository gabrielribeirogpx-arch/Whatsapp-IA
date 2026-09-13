from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.audit_log import AuditLog, _prevent_audit_log_delete, _prevent_audit_log_update
from app.services.audit_service import to_json_safe
from app.utils.log_sanitizer import sanitize_for_log, webhook_log_context


def test_operational_log_sanitizer_removes_secrets_and_content():
    sentinels = {
        "password": "SECRET_PASSWORD_VALUE",
        "access_token": "SECRET_ACCESS_TOKEN_VALUE",
        "api_key": "SECRET_API_KEY_VALUE",
        "message": "private customer message",
        "nested": {"authorization": "Bearer complete-jwt", "status": "ok"},
    }
    rendered = repr(sanitize_for_log(sentinels))
    for forbidden in ("SECRET_PASSWORD_VALUE", "SECRET_ACCESS_TOKEN_VALUE", "SECRET_API_KEY_VALUE", "private customer message", "Bearer complete-jwt"):
        assert forbidden not in rendered
    assert "'status': 'ok'" in rendered


def test_webhook_context_does_not_copy_customer_payload():
    raw = {"object": "whatsapp_business_account", "message": "private", "phone": "+5511999", "access_token": "secret"}
    rendered = repr(webhook_log_context(raw))
    assert "private" not in rendered
    assert "+5511999" not in rendered
    assert "secret" not in rendered
    assert "whatsapp_business_account" in rendered


def test_audit_metadata_recursively_redacts_prohibited_credentials():
    metadata = to_json_safe({"tenant_id": str(uuid4()), "nested": {"password": "SECRET_PASSWORD_VALUE", "access_token": "SECRET_ACCESS_TOKEN_VALUE", "api_key": "SECRET_API_KEY_VALUE"}})
    rendered = repr(metadata)
    assert "SECRET_PASSWORD_VALUE" not in rendered
    assert "SECRET_ACCESS_TOKEN_VALUE" not in rendered
    assert "SECRET_API_KEY_VALUE" not in rendered
    assert rendered.count("[REDACTED]") == 3


def test_audit_log_is_append_only_through_normal_orm_session():
    row = AuditLog(action="TEST", tenant_id=None)
    with pytest.raises(RuntimeError, match="append-only"):
        _prevent_audit_log_update(None, None, row)
    with pytest.raises(RuntimeError, match="append-only"):
        _prevent_audit_log_delete(None, None, row)


def test_whatsapp_router_requests_one_transaction(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from app.routers import whatsapp_providers as router

    tenant_id, user_id, provider_id = uuid4(), uuid4(), uuid4()
    provider = SimpleNamespace(id=provider_id, provider_type="meta_cloud")
    db = SimpleNamespace(refresh=lambda _row: None)
    observed = {}

    def create(_db, _tenant_id, _payload, *, commit=True):
        observed["service_commit"] = commit
        return provider

    def audit(_db, **kwargs):
        observed["audit_commit"] = kwargs["commit"]

    monkeypatch.setattr(router.whatsapp_provider_service, "create_provider", create)
    monkeypatch.setattr(router, "write_audit_log", audit)
    router.create_provider(
        request=SimpleNamespace(headers={}, client=None),
        payload=SimpleNamespace(provider_type="meta_cloud"),
        db=db,
        tenant=SimpleNamespace(id=tenant_id),
        user=SimpleNamespace(id=user_id),
    )
    assert observed == {"service_commit": False, "audit_commit": True}


def test_audit_tenant_fk_preserves_history_by_restricting_delete():
    foreign_key = next(iter(AuditLog.__table__.c.tenant_id.foreign_keys))
    assert foreign_key.ondelete == "RESTRICT"
