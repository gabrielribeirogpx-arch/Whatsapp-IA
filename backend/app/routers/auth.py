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

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PasswordResetToken, Tenant, TenantUser
from app.schemas.auth import ForgotPasswordRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, TenantAuthResponse
from app.security.turnstile import enforce_rate_limit, get_client_ip, validate_turnstile_or_raise
from app.services.audit_service import write_audit_log
from app.services.session_service import create_user_session

router = APIRouter(tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_WINDOW_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "1800"))


def _rate_identity(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


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


def _create_token(tenant_id: str, email: str, session_id: str | None = None) -> str:
    secret = os.getenv("AUTH_SECRET", "wazza-dev-secret")
    payload = {"tenant_id": tenant_id, "email": email, "iat": int(time.time()), "jti": secrets.token_urlsafe(12)}
    if session_id:
        payload["sid"] = session_id
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    sig_text = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{body}.{sig_text}"



def validate_password_policy(password: str) -> None:
    failures: list[str] = []
    if len(password) < 8:
        failures.append("mínimo 8 caracteres")
    if not re.search(r"[A-Z]", password):
        failures.append("1 letra maiúscula")
    if not re.search(r"[a-z]", password):
        failures.append("1 letra minúscula")
    if not re.search(r"\d", password):
        failures.append("1 número")
    if not re.search(r"[^A-Za-z0-9]", password):
        failures.append("1 caractere especial")
    if failures:
        print("[PASSWORD POLICY FAILED]", "missing=" + ",".join(failures))
        raise HTTPException(status_code=400, detail="Senha fraca: inclua " + ", ".join(failures))

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
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    client_ip = get_client_ip(request)
    email_hash = _rate_identity(email)
    enforce_rate_limit(key=f"forgot:ip:{client_ip}", limit=10, window_seconds=900)
    enforce_rate_limit(key=f"forgot:email:{email_hash}", limit=4, window_seconds=3600)
    validate_turnstile_or_raise(token=payload.turnstile_token, request=request, action="forgot-password")
    print("[PASSWORD RESET REQUEST]", f"email_hint={email[:2]}***")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email inválido")

    user = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if user:
        print("[PASSWORD RESET USER FOUND]", f"user_id={user.id}")
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=RESET_WINDOW_SECONDS)
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
        write_audit_log(db, action="PASSWORD_RESET_REQUESTED", tenant_id=user.tenant_id, user_id=user.id, entity_type="tenant_user", entity_id=user.id, metadata={"email_hint": email[:2] + "***"}, request=request)
        db.commit()
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        _send_reset_email(email, f"{frontend_url}/reset-password?token={raw_token}")
        print("[PASSWORD RESET EMAIL SENT]", f"user_id={user.id}")
    return {"message": "Se o email existir, enviaremos as instruções de recuperação."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")
    validate_password_policy(payload.new_password)

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
    user.password_changed_at = datetime.utcnow()
    token_row.used_at = datetime.now(timezone.utc)
    write_audit_log(db, action="PASSWORD_RESET_COMPLETED", tenant_id=user.tenant_id, user_id=user.id, entity_type="tenant_user", entity_id=user.id, request=request)
    db.commit()
    print("[PASSWORD RESET SUCCESS]", f"user_id={user.id}")
    return {"message": "Senha redefinida com sucesso."}


@router.post("/register", response_model=TenantAuthResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    email_hash = _rate_identity(payload.email)
    enforce_rate_limit(key=f"register:ip:{client_ip}", limit=8, window_seconds=3600)
    enforce_rate_limit(key=f"register:email:{email_hash}", limit=3, window_seconds=3600)
    validate_turnstile_or_raise(token=payload.turnstile_token, request=request, action="register")

    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")
    validate_password_policy(payload.password)
    if not EMAIL_RE.match(payload.email.strip().lower()):
        raise HTTPException(status_code=400, detail="Email inválido")

    email = payload.email.strip().lower()
    existing_email = db.execute(select(TenantUser.id).where(TenantUser.email == email)).scalars().first()
    if existing_email is not None:
        raise HTTPException(status_code=409, detail="Não foi possível criar a conta com estes dados")

    tenant = Tenant(name=payload.business_name.strip(), slug=_build_unique_slug(db, payload.business_name), phone_number_id=payload.whatsapp_number.strip(), ai_mode="vendedor")
    db.add(tenant)
    db.flush()

    owner = TenantUser(tenant_id=tenant.id, full_name=payload.full_name.strip(), email=email, password_hash=_hash_password(payload.password), role="owner")
    db.add(owner)
    db.flush()
    write_audit_log(db, action="USER_CREATED", tenant_id=tenant.id, user_id=owner.id, entity_type="tenant_user", entity_id=owner.id, metadata={"source": "register"}, request=request)
    token = _create_token(str(tenant.id), owner.email, session_id=str(owner.id))
    create_user_session(db, tenant_id=tenant.id, user_id=owner.id, token=token, request=request)
    db.commit()
    db.refresh(tenant)

    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)


@router.post("/login", response_model=TenantAuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    client_ip = get_client_ip(request)
    email_hash = _rate_identity(email)
    enforce_rate_limit(key=f"login:ip:{client_ip}", limit=20, window_seconds=900)
    enforce_rate_limit(key=f"login:email:{email_hash}", limit=8, window_seconds=900)
    validate_turnstile_or_raise(token=payload.turnstile_token, request=request, action="login")

    user = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if not user or not _verify_password(payload.password, user.password_hash):
        write_audit_log(db, action="LOGIN_FAILED", tenant_id=user.tenant_id if user else None, user_id=user.id if user else None, entity_type="tenant_user", entity_id=user.id if user else None, metadata={"email_hint": email[:2] + "***"}, request=request, commit=True)
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    tenant = db.execute(select(Tenant).where(Tenant.id == user.tenant_id)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    user.last_login_at = datetime.utcnow()
    db.add(user)
    token = _create_token(str(tenant.id), user.email, session_id=str(user.id))
    create_user_session(db, tenant_id=tenant.id, user_id=user.id, token=token, request=request)
    write_audit_log(db, action="LOGIN_SUCCESS", tenant_id=tenant.id, user_id=user.id, entity_type="tenant_user", entity_id=user.id, request=request)
    db.commit()

    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)
