from __future__ import annotations

import re
import unicodedata
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.security import create_tenant_token
from app.schemas.auth import TenantAuthResponse, TenantProfileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone_number_id: str = Field(min_length=2, max_length=64)


class LoginRequest(BaseModel):
    phone_number_id: str = Field(min_length=2, max_length=64)


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


@router.post("/register", response_model=TenantAuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    phone_number_id = payload.phone_number_id.strip()

    existing_phone = db.execute(select(Tenant.id).where(Tenant.phone_number_id == phone_number_id)).scalars().first()
    if existing_phone is not None:
        raise HTTPException(status_code=409, detail="phone_number_id já cadastrado")

    tenant = Tenant(
        name=payload.name.strip(),
        slug=_build_unique_slug(db, payload.name),
        phone_number_id=phone_number_id,
        ai_mode="vendedor",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return TenantAuthResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
        token=create_tenant_token(str(tenant.id), tenant.slug),
    )


@router.post("/login", response_model=TenantAuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    phone_number_id = payload.phone_number_id.strip()
    tenant = db.execute(select(Tenant).where(Tenant.phone_number_id == phone_number_id)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    return TenantAuthResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
        token=create_tenant_token(str(tenant.id), tenant.slug),
    )


@router.get("/me", response_model=TenantProfileResponse)
def my_account(tenant: Tenant = Depends(get_current_tenant)):
    return TenantProfileResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        phone_number_id=tenant.phone_number_id,
        plan=tenant.plan,
        language=tenant.language,
    )
