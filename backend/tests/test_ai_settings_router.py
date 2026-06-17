import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

BACKEND_IMPORT_ERROR = None
try:
    from app.routers.ai_settings import test_ai_settings
    from app.schemas.ai_settings import TenantAISettingsTestRequest
except ModuleNotFoundError as exc:
    if exc.name not in {"fastapi", "sqlalchemy", "pydantic"}:
        raise
    BACKEND_IMPORT_ERROR = exc


class _EmptyScalars:
    def first(self):
        return None


class _EmptyResult:
    def scalars(self):
        return _EmptyScalars()


class _EmptyDb:
    def execute(self, _statement):
        return _EmptyResult()


@unittest.skipIf(BACKEND_IMPORT_ERROR is not None, f"Backend dependency not installed: {getattr(BACKEND_IMPORT_ERROR, 'name', '')}")
class AISettingsRouterTest(unittest.TestCase):
    def test_test_endpoint_passes_manual_model_to_provider(self):
        tenant = SimpleNamespace(id=uuid4())
        payload = TenantAISettingsTestRequest(provider="gemini", chat_model="gemini-3.1-flash-lite", api_key="test-key")

        with patch("app.routers.ai_settings.test_provider_connection") as mocked_test:
            response = test_ai_settings(payload, tenant=tenant, db=_EmptyDb())

        self.assertTrue(response.ok)
        mocked_test.assert_called_once_with("gemini", "test-key", chat_model="gemini-3.1-flash-lite")

    def test_test_endpoint_allows_wazza_default_without_model_or_tenant_key(self):
        tenant = SimpleNamespace(id=uuid4())
        payload = TenantAISettingsTestRequest(provider="wazza_default")

        with patch("app.routers.ai_settings.test_provider_connection") as mocked_test:
            response = test_ai_settings(payload, tenant=tenant, db=_EmptyDb())

        self.assertTrue(response.ok)
        mocked_test.assert_called_once_with("wazza_default", "", chat_model=None)


if __name__ == "__main__":
    unittest.main()
