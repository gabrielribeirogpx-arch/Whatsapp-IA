from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def register_processed_message(db: Session, tenant_id: uuid.UUID, message_id: str) -> bool:
    if not message_id:
        return True

    query = text(
        """
        INSERT INTO processed_messages (message_id, tenant_id)
        VALUES (:message_id, :tenant_id)
        ON CONFLICT (message_id) DO NOTHING
        RETURNING message_id
        """
    )
    inserted = db.execute(query, {"message_id": message_id, "tenant_id": tenant_id}).scalar_one_or_none()
    return inserted is not None
