import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from backend.app.db.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), index=True)
    text: Mapped[str] = mapped_column(String)
    from_me: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")

    @validates("conversation")
    def _sync_tenant_from_conversation(self, key: str, conversation):
        if conversation is not None and getattr(conversation, "tenant_id", None) is not None:
            self.tenant_id = conversation.tenant_id
        return conversation

    @property
    def phone(self) -> str | None:
        return self.conversation.phone_number if self.conversation else None

    @property
    def content(self) -> str:
        return self.text

    @property
    def timestamp(self) -> datetime:
        return self.created_at
