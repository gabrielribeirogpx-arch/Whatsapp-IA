from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, TenantUser
from app.schemas.auth import LoginRequest, RegisterRequest, TenantAuthResponse

router = APIRouter(tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


@router.post("/register", response_model=TenantAuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    print("[AUTH REGISTER REQUEST]", payload.email)
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")
    if not EMAIL_RE.match(payload.email.strip().lower()):
        raise HTTPException(status_code=400, detail="Email inválido")

    email = payload.email.strip().lower()
    existing_email = db.execute(select(TenantUser.id).where(TenantUser.email == email)).scalars().first()
    if existing_email is not None:
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    tenant = Tenant(
        name=payload.business_name.strip(),
        slug=_build_unique_slug(db, payload.business_name),
        phone_number_id=payload.whatsapp_number.strip(),
        ai_mode="vendedor",
    )
    db.add(tenant)
    db.flush()
    print("[AUTH TENANT CREATED]", tenant.id)

    owner = TenantUser(
        tenant_id=tenant.id,
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=_hash_password(payload.password),
        role="owner",
    )
    db.add(owner)
    db.commit()
    db.refresh(tenant)
    print("[AUTH OWNER CREATED]", owner.id)

    token = _create_token(str(tenant.id), owner.email)
    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)


@router.post("/login", response_model=TenantAuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if not user or not _verify_password(payload.password, user.password_hash):
        print("[AUTH LOGIN FAILED]", email)
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    tenant = db.execute(select(Tenant).where(Tenant.id == user.tenant_id)).scalars().first()
    if not tenant:
        print("[AUTH LOGIN FAILED]", email)
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    print("[AUTH LOGIN SUCCESS]", email)
    token = _create_token(str(tenant.id), user.email)
    return TenantAuthResponse(tenant_id=tenant.id, slug=tenant.slug, token=token)
