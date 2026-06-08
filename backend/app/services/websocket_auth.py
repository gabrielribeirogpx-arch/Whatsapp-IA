from __future__ import annotations

from uuid import UUID

from fastapi import WebSocketException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TenantUser, UserSession
from app.routers.account import _decode_token
from app.services.session_service import hash_session_token


def authenticate_ws_user(db: Session, tenant_id: UUID, token: str) -> TenantUser:
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    payload = _decode_token(token)
    if str(payload.get("tenant_id")) != str(tenant_id):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    user = db.execute(
        select(TenantUser).where(TenantUser.tenant_id == tenant_id, TenantUser.email == email)
    ).scalars().first()
    if not user:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    token_hash = hash_session_token(token)
    session = db.execute(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    ).scalars().first()
    if session and session.revoked_at is not None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    return user
