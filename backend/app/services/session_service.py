from __future__ import annotations

import hashlib
import re
from datetime import datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import UserSession
from app.security.turnstile import get_client_ip


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def describe_device(user_agent: str | None) -> str:
    ua = user_agent or ""
    browser = "Navegador"
    if "Edg/" in ua:
        browser = "Edge"
    elif "Chrome/" in ua and "Chromium" not in ua:
        browser = "Chrome"
    elif "Safari/" in ua and "Chrome/" not in ua:
        browser = "Safari"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Postman" in ua:
        browser = "Postman"

    os_name = "Dispositivo"
    if "Windows" in ua:
        os_name = "Windows"
    elif "iPhone" in ua:
        os_name = "iPhone"
    elif "iPad" in ua:
        os_name = "iPad"
    elif "Android" in ua:
        os_name = "Android"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    return f"{browser} {os_name}"


def create_user_session(db: Session, *, tenant_id: UUID, user_id: UUID, token: str, request: Request) -> UserSession:
    user_agent = request.headers.get("user-agent")
    row = UserSession(
        tenant_id=tenant_id,
        user_id=user_id,
        session_token_hash=hash_session_token(token),
        ip_address=get_client_ip(request),
        user_agent=user_agent,
        device_name=describe_device(user_agent),
        last_seen_at=datetime.utcnow(),
    )
    db.add(row)
    print("[SESSION CREATED]", f"tenant_id={tenant_id}", f"user_id={user_id}", f"device={row.device_name}")
    return row


def serialize_user_session(row: UserSession, *, current_token_hash: str | None = None) -> dict[str, str | None | bool]:
    return {
        "id": str(row.id),
        "device": row.device_name or describe_device(row.user_agent),
        "ip_address": row.ip_address,
        "location": row.ip_address,
        "user_agent": row.user_agent,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "status": "Revogada" if row.revoked_at else "Ativa",
        "is_current": bool(current_token_hash and row.session_token_hash == current_token_hash),
    }
