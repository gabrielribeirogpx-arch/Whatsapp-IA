import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.mixins import TenantMixin


class Message(TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conversation_time", "conversation_id", "created_at"),
        Index("idx_messages_tenant_time", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), index=True)
    text: Mapped[str] = mapped_column(String)
    # Interactive replies keep their stable provider ID in ``text`` so flow
    # routing remains unchanged.  The optional title is presentation-only.
    interactive_title: Mapped[str | None] = mapped_column(String, nullable=True)
    from_me: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages", lazy="select")

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
        return self.interactive_title or self.text

    @property
    def technical_payload(self) -> str | None:
        return self.text if self.interactive_title else None

    @property
    def role(self) -> str:
        return "assistant" if self.from_me else "user"

    @property
    def timestamp(self) -> datetime:
        return self.created_at
