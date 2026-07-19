from __future__ import annotations

from types import SimpleNamespace
import unittest

BACKEND_IMPORT_ERROR = None
try:
    from app.routers.settings import _serialize_settings
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "sqlalchemy", "pydantic"}:
        raise
    BACKEND_IMPORT_ERROR = exc


@unittest.skipIf(BACKEND_IMPORT_ERROR is not None, f"Backend dependency not installed: {getattr(BACKEND_IMPORT_ERROR, 'name', '')}")
def test_settings_response_never_contains_whatsapp_access_token() -> None:
    tenant = SimpleNamespace(
        whatsapp_token="EAAB-secret-value-that-must-not-leave-the-server",
        phone_number_id="123456789",
        name="Tenant A",
        language="pt-BR",
        workspace_profile="private_sales",
    )

    response = _serialize_settings(tenant)
    data = response.model_dump() if hasattr(response, "model_dump") else response.dict()

    assert data["has_whatsapp_token"] is True
    assert "token" not in data
    assert "whatsapp_token" not in data
    assert "EAAB-secret-value-that-must-not-leave-the-server" not in str(data)


@unittest.skipIf(BACKEND_IMPORT_ERROR is not None, f"Backend dependency not installed: {getattr(BACKEND_IMPORT_ERROR, 'name', '')}")
def test_settings_response_reports_missing_token_without_exposing_fields() -> None:
    tenant = SimpleNamespace(
        whatsapp_token=None,
        phone_number_id=None,
        name="Tenant B",
        language="pt-BR",
        workspace_profile="private_sales",
    )

    response = _serialize_settings(tenant)
    data = response.model_dump() if hasattr(response, "model_dump") else response.dict()

    assert data["has_whatsapp_token"] is False
    assert set(data) == {
        "has_whatsapp_token",
        "phone_number_id",
        "system_name",
        "language",
        "workspace_profile",
    }
