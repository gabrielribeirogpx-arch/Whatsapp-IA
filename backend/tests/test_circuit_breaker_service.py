from __future__ import annotations

import time
import uuid
from unittest.mock import Mock

import pytest
import requests

from app.services import circuit_breaker_service as cb
from app.services.circuit_breaker_service import CircuitBreakerOpen
from app.services.llm_service import _circuit_key, _is_tenant_config_provider_error, _is_transient_provider_error
from app.services.mcp_service import call_mcp_tool


class DummyRedis:
    def __init__(self):
        self.data = {}

    def ping(self):
        return True

    def get(self, key):
        item = self.data.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.time():
            self.data.pop(key, None)
            return None
        return value

    def setex(self, key, ttl, value):
        self.data[key] = (time.time() + ttl, value)


def setup_function():
    cb._LOCAL_STATE.clear()


@pytest.fixture
def redis(monkeypatch):
    client = DummyRedis()
    monkeypatch.setattr(cb, "_redis", lambda: client)
    return client


def test_circuito_fechado_permite_chamada(redis):
    assert cb.check_circuit("provider:openai:gpt")["circuit_breaker_open"] is False


def test_falhas_abrem_e_circuito_aberto_bloqueia(redis):
    key = "provider:gemini:model"
    cb.record_failure(key, "timeout")
    meta = cb.record_failure(key, "status:503")
    assert meta["circuit_breaker_open"] is True
    with pytest.raises(CircuitBreakerOpen):
        cb.check_circuit(key, failure_threshold=2, cooldown_seconds=30)


def test_cooldown_entra_half_open_sucesso_fecha(redis):
    key = "provider:anthropic:model"
    cb.record_failure(key, "timeout")
    cb.record_failure(key, "timeout")
    meta = cb.check_circuit(key, failure_threshold=2, success_threshold=1, cooldown_seconds=0)
    assert meta["circuit_breaker_state"] == "half_open"
    meta = cb.record_success(key)
    assert meta["circuit_breaker_state"] == "closed"


def test_falha_em_half_open_reabre(redis):
    key = "mcp:tenant:server"
    cb.record_failure(key, "timeout")
    cb.record_failure(key, "timeout")
    cb.check_circuit(key, failure_threshold=2, cooldown_seconds=0)
    meta = cb.record_failure(key, "timeout")
    assert meta["circuit_breaker_state"] == "open"


def test_api_key_invalida_nao_abre_circuito_global(redis):
    tenant_id = uuid.uuid4()
    assert _is_tenant_config_provider_error(401, "invalid_api_key", "invalid api key") is True
    assert _is_transient_provider_error(401, "invalid_api_key", "invalid api key") is False
    global_key = _circuit_key("openai", "gpt-4o-mini", tenant_id)
    tenant_key = _circuit_key("openai", "gpt-4o-mini", tenant_id, config_error=True)
    cb.record_failure(tenant_key, "tenant_config:401")
    assert cb.check_circuit(global_key)["circuit_breaker_state"] == "closed"


def test_redis_indisponivel_nao_derruba_app(monkeypatch):
    monkeypatch.setattr(cb, "_redis", lambda: None)
    assert cb.check_circuit("provider:openai:gpt")["circuit_breaker_open"] is False
    cb.record_failure("provider:openai:gpt", "timeout")


def test_reason_sanitizado():
    safe = cb.sanitize_reason("https://x.test?a=1&token=secret Authorization: Bearer abc")
    assert "secret" not in safe
    assert "abc" not in safe
    assert "[REDACTED]" in safe


def test_mcp_open_retorna_status_circuit_open(monkeypatch):
    tenant_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    server_id = uuid.uuid4()
    tool = Mock(id=tool_id, server_id=server_id, is_enabled=True, input_schema={"type": "object"}, tool_name="buscar")
    server = Mock(id=server_id, is_enabled=True, server_url="https://mcp.example.com", encrypted_config={})
    monkeypatch.setattr("app.services.mcp_service._tool", lambda db, tenant, parsed: tool)
    monkeypatch.setattr("app.services.mcp_service._server", lambda db, tenant, parsed: server)
    monkeypatch.setattr("app.services.mcp_service.check_circuit", Mock(side_effect=CircuitBreakerOpen()))
    result = call_mcp_tool(Mock(), tenant_id, tool_id, {})
    assert result["status"] == "circuit_open"


def test_call_with_circuit_registra_sucesso_e_falha(redis):
    assert cb.call_with_circuit("webhook:t:h", lambda: "ok") == "ok"
    with pytest.raises(requests.Timeout):
        cb.call_with_circuit("webhook:t:h2", lambda: (_ for _ in ()).throw(requests.Timeout()))
