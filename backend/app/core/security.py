from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import jwt
from fastapi import HTTPException

ALGORITHM = "HS256"
DEFAULT_EXP_MINUTES = 60 * 24 * 7


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "change-me-in-production")


def create_tenant_token(tenant_id: str, slug: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_EXP_MINUTES)
    payload = {
        "sub": tenant_id,
        "tenant_id": tenant_id,
        "slug": slug,
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def decode_tenant_token(token: str) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Token inválido") from exc
