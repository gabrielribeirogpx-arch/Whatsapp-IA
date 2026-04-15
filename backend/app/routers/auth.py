from __future__ import annotations

import re
import unicodedata
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.schemas.auth import TenantAuthResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Tenant

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone_number_id: str = Field(min_length=2, max_length=64)


class LoginRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=80)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "tenant"


def _build_unique_slug(db: Session, name: str) -> str:
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 1

    while db.execute(select(Tenant.id).where(Tenant.slug == slug)).scalar_one_or_none() is not None:
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    return slug


@router.post("/register", response_model=TenantAuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    phone_number_id = payload.phone_number_id.strip()

    existing_phone = db.execute(select(Tenant.id).where(Tenant.phone_number_id == phone_number_id)).scalar_one_or_none()
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
    )


@router.post("/login", response_model=TenantAuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    tenant = db.execute(select(Tenant).where(Tenant.slug == payload.slug.strip())).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    return TenantAuthResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
    )
