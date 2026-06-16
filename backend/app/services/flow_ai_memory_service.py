from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.flow_ai_conversation_message import FlowAIConversationMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 10
DEFAULT_MAX_CHARS = 4000
ROLE_LABELS = {"user": "Usuário", "assistant": "Assistente", "system": "Sistema"}

# TODO: Futuro: política de retenção por tenant.
# TODO: Futuro: anonimização/expurgo.
# TODO: Futuro: opção de desativar memória por workspace.


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _external_message_id(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("external_message_id", "message_id", "correlation_id", "input_message_id"):
        value = metadata.get(key)
        if value:
            return str(value)
    return None


class FlowAIMemoryService:
    def append_user_message(self, db: Session, **kwargs: Any) -> FlowAIConversationMessage | None:
        return self._append_message(db, role="user", **kwargs)

    def append_assistant_message(self, db: Session, **kwargs: Any) -> FlowAIConversationMessage | None:
        return self._append_message(db, role="assistant", **kwargs)

    def _append_message(
        self,
        db: Session,
        *,
        tenant_id: uuid.UUID,
        flow_id: uuid.UUID,
        flow_version_id: uuid.UUID | None,
        session_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
        node_id: str | uuid.UUID,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> FlowAIConversationMessage | None:
        content = str(content or "").strip()
        node_uuid = _as_uuid(node_id)
        if not content or node_uuid is None:
            return None
        safe_metadata = dict(metadata or {})
        external_message_id = _external_message_id(safe_metadata)
        if role == "user" and external_message_id:
            existing = db.execute(
                select(FlowAIConversationMessage).where(
                    FlowAIConversationMessage.tenant_id == tenant_id,
                    FlowAIConversationMessage.session_id == session_id,
                    FlowAIConversationMessage.role == "user",
                    FlowAIConversationMessage.metadata_json["external_message_id"].astext == external_message_id,
                )
            ).scalars().first()
            if existing:
                logger.info("[AI MEMORY] append_skipped_duplicate role=user tenant_id=%s session_id=%s node_id=%s external_message_id=%s", tenant_id, session_id, node_uuid, external_message_id)
                return existing
            safe_metadata["external_message_id"] = external_message_id
        row = FlowAIConversationMessage(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            session_id=session_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            node_id=node_uuid,
            role=role,
            content=content,
            metadata_json=safe_metadata or None,
        )
        db.add(row)
        db.flush()
        logger.info("[AI MEMORY] append role=%s tenant_id=%s session_id=%s node_id=%s external_message_id=%s", role, tenant_id, session_id, node_uuid, external_message_id)
        return row

    def get_recent_history(self, db: Session, *, tenant_id: uuid.UUID, session_id: uuid.UUID, max_messages: int = DEFAULT_MAX_MESSAGES, max_chars: int = DEFAULT_MAX_CHARS) -> list[FlowAIConversationMessage]:
        max_messages = max(1, int(max_messages or DEFAULT_MAX_MESSAGES))
        max_chars = max(1, int(max_chars or DEFAULT_MAX_CHARS))
        rows = list(db.execute(select(FlowAIConversationMessage).where(FlowAIConversationMessage.tenant_id == tenant_id, FlowAIConversationMessage.session_id == session_id).order_by(FlowAIConversationMessage.created_at.desc(), FlowAIConversationMessage.id.desc()).limit(max_messages * 3)).scalars().all())
        selected: list[FlowAIConversationMessage] = []
        chars = 0
        for row in rows:
            content = (row.content or "").strip()
            if not content:
                continue
            if selected and chars + len(content) > max_chars:
                break
            selected.append(row)
            chars += len(content)
            if len(selected) >= max_messages:
                break
        selected.reverse()
        logger.info("[AI MEMORY] history tenant_id=%s session_id=%s messages=%s chars=%s", tenant_id, session_id, len(selected), chars)
        return selected

    def build_history_for_prompt(self, messages: list[FlowAIConversationMessage]) -> str:
        lines = []
        for message in messages:
            content = (message.content or "").strip()
            if content:
                lines.append(f"{ROLE_LABELS.get(message.role, message.role)}: {content}")
        return "\n".join(lines)

    def has_assistant_message(self, db: Session, *, tenant_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        return db.execute(select(FlowAIConversationMessage.id).where(FlowAIConversationMessage.tenant_id == tenant_id, FlowAIConversationMessage.session_id == session_id, FlowAIConversationMessage.role == "assistant").limit(1)).first() is not None


flow_ai_memory_service = FlowAIMemoryService()
