from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PasswordResetToken, Tenant, TenantUser
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, TenantAuthResponse

router = APIRouter(tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_WINDOW_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "1800"))


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "tenant"


def _build_unique_slug(db: Session, name: str) -> str:
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 1
    while db.execute(select(Tenant.id).where(Tenant.slug == slug)).scalars().first() is not None:
        suffix += 1
        slug = f"{base_slug}-{suffix}"
    return slug


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        _, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    expected = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, digest)


def _create_token(tenant_id: str, email: str) -> str:
    secret = os.getenv("AUTH_SECRET", "wazza-dev-secret")
    payload = {"tenant_id": tenant_id, "email": email, "iat": int(time.time())}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    sig_text = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{body}.{sig_text}"


def _hash_reset_token(token: str) -> str:
    secret = os.getenv("PASSWORD_RESET_SECRET", os.getenv("AUTH_SECRET", "wazza-dev-secret"))
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _send_reset_email(email: str, reset_link: str) -> None:
    resend_api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("RESEND_FROM_EMAIL", "no-reply@wazza.local")
    masked = f"{email[:2]}***@***"
    if not resend_api_key:
        print(f"[PASSWORD RESET REQUEST] provider=mock target={masked} link={reset_link[:60]}...")
        return

    try:
        import requests
        payload = {
            "from": sender,
            "to": [email],
            "subject": "Redefinição de senha · Wazza API",
            "html": f"""
            <div style='font-family:Inter,Arial,sans-serif;padding:24px;background:#f4f7ff;color:#0f172a'>
              <h2 style='margin:0 0 12px'>Redefinir sua senha</h2>
              <p style='margin:0 0 16px'>Seu link expira em 30 minutos e só pode ser usado uma vez.</p>
              <a href='{reset_link}' style='display:inline-block;padding:12px 18px;border-radius:10px;background:#4f46e5;color:white;text-decoration:none;font-weight:600'>Redefinir senha</a>
            </div>
            """,
        }
        requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=5,
        )
    except Exception as exc:
        print(f"[PASSWORD RESET REQUEST] provider=resend status=error error={type(exc).__name__}")


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email inválido")

    user = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=RESET_WINDOW_SECONDS)
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
        db.commit()
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        _send_reset_email(email, f"{frontend_url}/reset-password?token={raw_token}")
    print("[PASSWORD RESET REQUEST]", f"email_hint={email[:2]}***")
    return {"message": "Se o email existir, enviaremos as instruções de recuperação."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")

    token_hash = _hash_reset_token(payload.token)
    token_row = db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)).scalars().first()
    if not token_row or token_row.used_at is not None or token_row.expires_at < datetime.now(timezone.utc):
        print("[PASSWORD RESET INVALID TOKEN]")
        raise HTTPException(status_code=400, detail="Token inválido ou expirado")

    user = db.execute(select(TenantUser).where(TenantUser.id == token_row.user_id)).scalars().first()
    if not user:
        print("[PASSWORD RESET INVALID TOKEN]")
        raise HTTPException(status_code=400, detail="Token inválido ou expirado")

    user.password_hash = _hash_password(payload.new_password)
    token_row.used_at = datetime.now(timezone.utc)
    db.commit()
    print("[PASSWORD RESET SUCCESS]", f"user_id={user.id}")
    return {"message": "Senha redefinida com sucesso."}


@router.post("/register", response_model=TenantAuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")
    if not EMAIL_RE.match(payload.email.strip().lower()):
        raise HTTPException(status_code=400, detail="Email inválido")

    email = payload.email.strip().lower()
    existing_email = db.execute(select(TenantUser.id).where(TenantUser.email == email)).scalars().first()
    if existing_email is not None:
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    tenant = Tenant(name=payload.business_name.strip(), slug=_build_unique_slug(db, payload.business_name), phone_number_id=payload.whatsapp_number.strip(), ai_mode="vendedor")
    db.add(tenant)
    db.flush()

    owner = TenantUser(tenant_id=tenant.id, full_name=payload.full_name.strip(), email=email, password_hash=_hash_password(payload.password), role="owner")
    db.add(owner)
    db.commit()
    db.refresh(tenant)

    token = _create_token(str(tenant.id), owner.email)
    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)


@router.post("/login", response_model=TenantAuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if not user or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    tenant = db.execute(select(Tenant).where(Tenant.id == user.tenant_id)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = _create_token(str(tenant.id), user.email)
    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)
