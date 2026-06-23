from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

from app.database import SessionLocal
from app.services.integration_connection_service import GOOGLE_CONNECTION_PROVIDERS, IntegrationConnectionService


def _row(connection: Any) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "tenant_id": str(connection.tenant_id),
        "provider": connection.provider,
        "auth_type": connection.auth_type,
        "status": connection.status,
        "has_access_token": bool(connection.access_token_encrypted),
        "has_refresh_token": bool(connection.refresh_token_encrypted),
        "expires_at": connection.expires_at.isoformat() if connection.expires_at else None,
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
        "metadata": connection.metadata_json or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Lista ou limpa conexões Google de um tenant.")
    parser.add_argument("tenant_id", help="UUID do tenant")
    parser.add_argument("--disconnect", action="store_true", help="Marca conexões Google como disconnected e limpa tokens.")
    args = parser.parse_args()
    tenant_id = uuid.UUID(args.tenant_id)
    db = SessionLocal()
    try:
        service = IntegrationConnectionService(db)
        if args.disconnect:
            service.disconnect_google_connections(tenant_id)
        rows = [c for c in service.list_connections(tenant_id) if c.provider in GOOGLE_CONNECTION_PROVIDERS]
        print(json.dumps([_row(c) for c in rows], ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
