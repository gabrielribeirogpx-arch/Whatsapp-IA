from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, TenantUser
from app.schemas.account import (
    AccountMeOut,
    AccountProfileOut,
    AccountProfileUpdateIn,
    AccountPreferencesOut,
    AccountPreferencesUpdateIn,
    AccountSecurityOut,
    AccountPasswordUpdateIn,
    WorkspaceUserInviteIn,
    WorkspaceUserOut,
    WorkspaceUserUpdateIn,
)
from app.services.tenant_service import get_current_tenant
from app.routers.auth import _hash_password, _verify_password

router = APIRouter(tags=["account"])


def _decode_token(token: str) -> dict:
    secret = os.getenv("AUTH_SECRET", "wazza-dev-secret")
    try:
        body, sig_text = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Token inválido") from exc
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    expected_text = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(expected_text, sig_text):
        raise HTTPException(status_code=401, detail="Token inválido")
    padded_body = body + "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded_body.encode()).decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Token inválido") from exc
    return payload


def get_current_user(
    request: Request,
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> TenantUser:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token obrigatório")
    payload = _decode_token(authorization.split(" ", 1)[1].strip())
    if str(payload.get("tenant_id")) != str(tenant.id):
        raise HTTPException(status_code=401, detail="Token não pertence ao tenant atual")
    email = str(payload.get("email") or "").strip().lower()
    user = db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant.id, TenantUser.email == email)).scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


def _profile(user: TenantUser, tenant: Tenant) -> AccountProfileOut:
    return AccountProfileOut(
        id=user.id,
        name=user.full_name,
        email=user.email,
        avatar_url=user.avatar_url,
        company=user.company or tenant.name,
        job_title=user.job_title,
        role=user.role,
    )


def _preferences(user: TenantUser, tenant: Tenant) -> AccountPreferencesOut:
    return AccountPreferencesOut(
        language=user.preferred_language or tenant.language or "pt-BR",
        timezone=user.timezone or "America/Sao_Paulo",
        email_notifications=user.email_notifications_enabled,
        whatsapp_notifications=user.whatsapp_notifications_enabled,
    )


def _workspace_user(user: TenantUser) -> WorkspaceUserOut:
    return WorkspaceUserOut(
        id=user.id,
        name=user.full_name,
        email=user.email,
        role=user.role,
        status=user.status,
        last_access_at=user.last_login_at,
    )


def _security(user: TenantUser) -> AccountSecurityOut:
    now = datetime.now(timezone.utc)
    active_sessions = [
        {
            "id": "current",
            "device": "Navegador atual",
            "location": "Sessão autenticada",
            "last_seen_at": (user.last_login_at or now).isoformat(),
            "status": "Ativa",
        }
    ]
    history = [
        {"event": "Conta criada", "description": "Administrador inicial do workspace", "created_at": user.created_at.isoformat() if user.created_at else None},
        {"event": "Último login", "description": "Acesso validado por senha", "created_at": user.last_login_at.isoformat() if user.last_login_at else None},
        {"event": "Senha atualizada", "description": "Credenciais protegidas com hash seguro", "created_at": user.password_changed_at.isoformat() if user.password_changed_at else None},
    ]
    return AccountSecurityOut(
        last_login_at=user.last_login_at,
        active_sessions=active_sessions,
        history=history,
        mfa_status="Em breve",
    )


@router.get("/account/me", response_model=AccountMeOut)
def get_account_me(tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return AccountMeOut(profile=_profile(user, tenant), preferences=_preferences(user, tenant), security=_security(user))


@router.put("/account/profile", response_model=AccountProfileOut)
def update_profile(payload: AccountProfileUpdateIn, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    user.full_name = payload.name.strip()
    user.email = payload.email.strip().lower()
    user.avatar_url = payload.avatar_url.strip() if payload.avatar_url else None
    user.company = payload.company.strip() if payload.company else tenant.name
    user.job_title = payload.job_title.strip() if payload.job_title else None
    db.add(user)
    db.commit()
    db.refresh(user)
    return _profile(user, tenant)


@router.put("/account/preferences", response_model=AccountPreferencesOut)
def update_preferences(payload: AccountPreferencesUpdateIn, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    user.preferred_language = payload.language.strip()
    user.timezone = payload.timezone.strip()
    user.email_notifications_enabled = payload.email_notifications
    user.whatsapp_notifications_enabled = payload.whatsapp_notifications
    tenant.language = payload.language.strip()
    db.add_all([user, tenant])
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    return _preferences(user, tenant)


@router.get("/account/security", response_model=AccountSecurityOut)
def get_security(user: TenantUser = Depends(get_current_user)):
    return _security(user)


@router.post("/account/security/password")
def update_password(payload: AccountPasswordUpdateIn, db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="As senhas não coincidem")
    if not _verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    user.password_hash = _hash_password(payload.new_password)
    user.password_changed_at = datetime.utcnow()
    db.add(user)
    db.commit()
    return {"message": "Senha alterada com sucesso."}


@router.get("/workspace/users", response_model=list[WorkspaceUserOut])
def list_workspace_users(tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user), db: Session = Depends(get_db)):
    users = db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant.id).order_by(TenantUser.created_at.asc())).scalars().all()
    return [_workspace_user(item) for item in users]


@router.post("/workspace/users", response_model=WorkspaceUserOut)
def invite_workspace_user(payload: WorkspaceUserInviteIn, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    email = payload.email.strip().lower()
    existing = db.execute(select(TenantUser).where(TenantUser.email == email)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado")
    invited = TenantUser(
        tenant_id=tenant.id,
        full_name=payload.name.strip(),
        email=email,
        password_hash=_hash_password(secrets.token_urlsafe(18)),
        role=payload.role,
        status="invited",
        company=tenant.name,
    )
    db.add(invited)
    db.commit()
    db.refresh(invited)
    return _workspace_user(invited)


@router.patch("/workspace/users/{user_id}", response_model=WorkspaceUserOut)
def update_workspace_user(user_id: UUID, payload: WorkspaceUserUpdateIn, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    target = db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant.id, TenantUser.id == user_id)).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if payload.name is not None:
        target.full_name = payload.name.strip()
    if payload.role is not None:
        target.role = payload.role
    if payload.status is not None:
        target.status = payload.status
    db.add(target)
    db.commit()
    db.refresh(target)
    return _workspace_user(target)


@router.post("/workspace/users/{user_id}/deactivate", response_model=WorkspaceUserOut)
def deactivate_workspace_user(user_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    target = db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant.id, TenantUser.id == user_id)).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Você não pode desativar a própria sessão administrativa")
    target.status = "inactive"
    db.add(target)
    db.commit()
    db.refresh(target)
    return _workspace_user(target)
