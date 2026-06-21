from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection

_AUTH_TYPES = {"oauth", "oauth2", "api_key"}
_PREFIX = "oauth:v1:"


class IntegrationConnectionConfigurationError(RuntimeError):
    """Raised when integration credential encryption is not configured."""


class IntegrationConnectionService:
    """Reusable tenant-scoped storage for third-party integration credentials."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def normalize_provider(provider: str) -> str:
        value = (provider or "").strip().lower()
        if not value:
            raise ValueError("Provider da integração é obrigatório")
        return value

    @staticmethod
    def normalize_auth_type(auth_type: str) -> Literal["oauth", "oauth2", "api_key"]:
        value = (auth_type or "").strip().lower()
        if value not in _AUTH_TYPES:
            raise ValueError("auth_type deve ser 'oauth', 'oauth2' ou 'api_key'")
        return value  # type: ignore[return-value]

    @staticmethod
    def _fernet() -> Fernet:
        raw_key = (os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "") or "").strip()
        if not raw_key:
            raise IntegrationConnectionConfigurationError("OAUTH_TOKEN_ENCRYPTION_KEY não configurada")
        try:
            if len(raw_key) == 44:
                return Fernet(raw_key.encode("utf-8"))
        except Exception:
            pass
        digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @classmethod
    def encrypt_credential(cls, value: str | None) -> str | None:
        if value is None:
            return None
        plain = value.strip()
        if not plain:
            return None
        if plain.startswith(_PREFIX):
            return plain
        encrypted = cls._fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
        return f"{_PREFIX}{encrypted}"

    @classmethod
    def decrypt_credential_strict(cls, value: str | None) -> str | None:
        if value is None:
            return None
        item = value.strip()
        if not item:
            return None
        if not item.startswith(_PREFIX):
            return item
        return cls._fernet().decrypt(item[len(_PREFIX) :].encode("utf-8")).decode("utf-8")

    @classmethod
    def decrypt_credential(cls, value: str | None) -> str | None:
        try:
            return cls.decrypt_credential_strict(value)
        except InvalidToken:
            return None

    def get_connection(self, tenant_id: uuid.UUID, provider: str) -> IntegrationConnection | None:
        provider = self.normalize_provider(provider)
        return self.db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == provider,
            )
        ).scalars().first()

    def get_active_connection(self, tenant_id: uuid.UUID, provider: str) -> IntegrationConnection | None:
        provider = self.normalize_provider(provider)
        return self.db.execute(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == provider,
                IntegrationConnection.status == "active",
            )
            .order_by(IntegrationConnection.updated_at.desc())
            .limit(1)
        ).scalars().first()

    def list_connections(self, tenant_id: uuid.UUID) -> list[IntegrationConnection]:
        return list(
            self.db.execute(
                select(IntegrationConnection)
                .where(IntegrationConnection.tenant_id == tenant_id)
                .order_by(IntegrationConnection.provider.asc())
            ).scalars().all()
        )

    def upsert_connection(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
        auth_type: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        api_key: str | None = None,
        expires_at: datetime | None = None,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
        commit: bool = True,
    ) -> IntegrationConnection:
        provider = self.normalize_provider(provider)
        auth_type = self.normalize_auth_type(auth_type)
        connection = self.get_connection(tenant_id, provider)
        if connection is None:
            connection = IntegrationConnection(tenant_id=tenant_id, provider=provider, auth_type=auth_type)
            self.db.add(connection)
        connection.auth_type = auth_type
        connection.status = status
        connection.expires_at = expires_at
        connection.scopes = scopes or []
        connection.metadata_json = metadata or {}
        connection.updated_at = datetime.utcnow()
        if access_token is not None:
            connection.access_token_encrypted = self.encrypt_credential(access_token)
        if refresh_token is not None:
            connection.refresh_token_encrypted = self.encrypt_credential(refresh_token)
        if api_key is not None:
            connection.api_key_encrypted = self.encrypt_credential(api_key)
        if commit:
            self.db.commit(); self.db.refresh(connection)
        return connection

    def update_tokens(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        api_key: str | None = None,
        expires_at: datetime | None = None,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> IntegrationConnection:
        connection = self.get_connection(tenant_id, provider)
        if connection is None:
            raise ValueError("Conexão de integração não encontrada")
        if access_token is not None:
            connection.access_token_encrypted = self.encrypt_credential(access_token)
        if refresh_token is not None:
            connection.refresh_token_encrypted = self.encrypt_credential(refresh_token)
        if api_key is not None:
            connection.api_key_encrypted = self.encrypt_credential(api_key)
        if expires_at is not None:
            connection.expires_at = expires_at
        if scopes is not None:
            connection.scopes = scopes
        if metadata is not None:
            connection.metadata_json = metadata
        connection.status = "active"
        connection.updated_at = datetime.utcnow()
        if commit:
            self.db.commit(); self.db.refresh(connection)
        return connection

    def disconnect_connection(self, tenant_id: uuid.UUID, provider: str, *, commit: bool = True) -> IntegrationConnection | None:
        connection = self.get_connection(tenant_id, provider)
        if connection is None:
            return None
        connection.status = "disconnected"
        connection.access_token_encrypted = None
        connection.refresh_token_encrypted = None
        connection.api_key_encrypted = None
        connection.expires_at = None
        connection.updated_at = datetime.utcnow()
        if commit:
            self.db.commit(); self.db.refresh(connection)
        return connection

    def is_connected(self, tenant_id: uuid.UUID, provider: str) -> bool:
        return self.get_active_connection(tenant_id, provider) is not None

    @staticmethod
    def to_public_status(connection: IntegrationConnection | None, provider: str | None = None) -> dict[str, Any]:
        normalized_provider = IntegrationConnectionService.normalize_provider(provider or (connection.provider if connection else "unknown"))
        if connection is None:
            return {
                "provider": normalized_provider,
                "auth_type": None,
                "status": "disconnected",
                "connected": False,
                "scopes": [],
                "metadata": {},
                "expires_at": None,
            }
        connected = connection.status == "active"
        return {
            "provider": connection.provider,
            "auth_type": connection.auth_type,
            "status": connection.status,
            "connected": connected,
            "scopes": connection.scopes or [],
            "metadata": connection.metadata_json or {},
            "expires_at": connection.expires_at,
        }
