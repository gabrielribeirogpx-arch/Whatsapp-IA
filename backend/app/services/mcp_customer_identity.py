"""Short-lived customer identity proof for outbound MCP calls."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import time
from typing import Any


CONTEXT_HEADER = "X-Wazza-Customer-Context"
SIGNATURE_HEADER = "X-Wazza-Customer-Signature"
CONTEXT_TTL_SECONDS = 60
_PHONE_PATTERN = re.compile(r"^[0-9]{8,15}$")


@dataclass(frozen=True)
class McpCustomerIdentity:
    phone: str
    conversation_id: str | None = None


def customer_identity_from_runtime(
    external_user_id: Any,
    conversation_id: Any | None = None,
) -> McpCustomerIdentity | None:
    try:
        phone = normalize_whatsapp_phone(external_user_id)
    except ValueError:
        return None
    return McpCustomerIdentity(
        phone=phone,
        conversation_id=str(conversation_id) if conversation_id else None,
    )


def normalize_whatsapp_phone(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"[0-9+().\s-]+", raw):
        raise ValueError("invalid_mcp_customer_phone")
    phone = re.sub(r"[^0-9]", "", raw)
    if not _PHONE_PATTERN.fullmatch(phone):
        raise ValueError("invalid_mcp_customer_phone")
    return phone


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def signed_customer_headers(
    *,
    bearer_token: str,
    identity: McpCustomerIdentity,
    request_id: str,
    now: int | None = None,
) -> dict[str, str]:
    if not str(bearer_token).strip():
        raise ValueError("missing_mcp_bearer_token")
    if not request_id or len(str(request_id)) > 128:
        raise ValueError("invalid_mcp_request_id")
    issued_at = int(time.time() if now is None else now)
    claims = {
        "aud": "fomizero-mcp",
        "exp": issued_at + CONTEXT_TTL_SECONDS,
        "iat": issued_at,
        "iss": "wazza",
        "rid": str(request_id),
        "sub": normalize_whatsapp_phone(identity.phone),
        "v": 1,
    }
    if identity.conversation_id:
        claims["cid"] = str(identity.conversation_id)[:128]
    encoded = _base64url(
        json.dumps(claims, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_key = hashlib.sha256(str(bearer_token).encode("utf-8")).digest()
    signature = _base64url(hmac.new(signing_key, encoded.encode("ascii"), hashlib.sha256).digest())
    return {CONTEXT_HEADER: encoded, SIGNATURE_HEADER: signature}
