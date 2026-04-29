from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.processed_message import ProcessedMessage


class IdempotencyService:
    def __init__(self, db: Session):
        self.db = db

    def is_duplicate(self, message_id: str) -> bool:
        if not message_id:
            return False
        return self.db.query(ProcessedMessage).filter_by(message_id=message_id).first() is not None

    def register(self, message_id: str) -> None:
        if not message_id:
            return
        record = ProcessedMessage(message_id=message_id)
        self.db.add(record)
        self.db.commit()


def register_processed_message(db: Session, tenant_id: uuid.UUID, message_id: str) -> bool:
    if not message_id:
        return True

    query = text(
        """
        INSERT INTO processed_messages (id, message_id, created_at)
        VALUES (:id, :message_id, :created_at)
        ON CONFLICT (message_id) DO NOTHING
        RETURNING message_id
        """
    )
    inserted = db.execute(
        query,
        {"id": uuid.uuid4(), "message_id": message_id, "created_at": datetime.utcnow()},
    ).scalar_one_or_none()
    return inserted is not None
