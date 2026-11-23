from __future__ import annotations

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
import uuid

import pytest

from app.services.mcp_customer_identity import (
    CONTEXT_HEADER,
    SIGNATURE_HEADER,
    McpCustomerIdentity,
    customer_identity_from_runtime,
    signed_customer_headers,
)


def _decode(value: str) -> dict:
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    return json.loads(raw)


def test_signed_context_is_short_lived_and_bound_to_request_and_customer():
    token = "fmz_mcp_key.secret"
    headers = signed_customer_headers(
        bearer_token=token,
        identity=McpCustomerIdentity(phone="+55 (11) 99999-9999", conversation_id="conversation-1"),
        request_id="request-1",
        now=1_800_000_000,
    )

    claims = _decode(headers[CONTEXT_HEADER])
    assert claims == {
        "aud": "fomizero-mcp",
        "cid": "conversation-1",
        "exp": 1_800_000_060,
        "iat": 1_800_000_000,
        "iss": "wazza",
        "rid": "request-1",
        "sub": "5511999999999",
        "v": 1,
    }
    key = hashlib.sha256(token.encode()).digest()
    expected = base64.urlsafe_b64encode(
        hmac.new(key, headers[CONTEXT_HEADER].encode("ascii"), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert hmac.compare_digest(headers[SIGNATURE_HEADER], expected)


def test_runtime_identity_fails_closed_for_non_whatsapp_identifiers():
    assert customer_identity_from_runtime("email@example.com") is None
    identity = customer_identity_from_runtime("5511988887777", "conversation")
    assert identity == McpCustomerIdentity("5511988887777", "conversation")


@pytest.mark.parametrize("phone", ["", "123", "not-a-phone", "customer5511999999999"])
def test_signer_rejects_invalid_phone(phone):
    with pytest.raises(ValueError, match="invalid_mcp_customer_phone"):
        signed_customer_headers(
            bearer_token="token",
            identity=McpCustomerIdentity(phone),
            request_id="request",
            now=1,
        )


def test_mcp_call_sends_identity_bound_to_json_rpc_request(monkeypatch):
    from app.services import mcp_service

    tool_id = uuid.uuid4()
    server_id = uuid.uuid4()
    token = "fmz_mcp_0123456789abcdef.a_secure_test_token_with_enough_length"
    tool = SimpleNamespace(
        id=tool_id,
        server_id=server_id,
        tool_name="customer_get_profile",
        input_schema={"type": "object", "additionalProperties": False},
        is_enabled=True,
    )
    server = SimpleNamespace(
        id=server_id,
        server_url="https://fomizero.example/mcp",
        encrypted_config=None,
        is_enabled=True,
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jsonrpc": "2.0", "id": "ignored", "result": {"structuredContent": {"ok": True}}}

    monkeypatch.setattr(mcp_service, "_tool", lambda *_args: tool)
    monkeypatch.setattr(mcp_service, "_server", lambda *_args: server)
    monkeypatch.setattr(mcp_service, "_decrypt_config", lambda _config: {"bearer_token": token})
    monkeypatch.setattr(mcp_service, "check_circuit", lambda _key: {})
    monkeypatch.setattr(mcp_service, "record_success", lambda _key: None)
    monkeypatch.setattr(mcp_service, "record_event", lambda *_args, **_kwargs: None)

    def post(url, *, headers, json, timeout):
        captured.update(url=url, headers=headers, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(mcp_service.requests, "post", post)
    result = mcp_service.call_mcp_tool(
        SimpleNamespace(),
        uuid.uuid4(),
        tool_id,
        {},
        customer_identity=McpCustomerIdentity("5511999999999", "conversation-1"),
    )

    assert result["ok"] is True
    claims = _decode(captured["headers"][CONTEXT_HEADER])
    assert claims["rid"] == captured["payload"]["id"]
    assert claims["sub"] == "5511999999999"
    assert claims["cid"] == "conversation-1"
    assert SIGNATURE_HEADER in captured["headers"]
