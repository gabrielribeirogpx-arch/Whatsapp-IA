from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    phone_number_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    verify_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="starter")
    max_monthly_messages: Mapped[int] = mapped_column(Integer, default=1000)
    usage_month: Mapped[str] = mapped_column(String(7), default=lambda: datetime.utcnow().strftime("%Y-%m"))
    messages_used_month: Mapped[int] = mapped_column(Integer, default=0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_password: Mapped[str] = mapped_column(String(255), default="admin123")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    ai_config: Mapped["AIConfig | None"] = relationship(back_populates="tenant", uselist=False, cascade="all, delete-orphan")


class AIConfig(Base):
    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    system_prompt: Mapped[str] = mapped_column(
        Text,
        default=(
            "Você é um atendente profissional de WhatsApp para uma empresa de tecnologia. "
            "Responda de forma objetiva, cordial e com foco em resolver o problema do cliente."
        ),
    )
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, default=0.4)

    tenant: Mapped[Tenant] = relationship(back_populates="ai_config")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_conversation_tenant_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(150), default="Cliente")
    status: Mapped[str] = mapped_column(String(16), default="bot", index=True)
    last_message: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    tenant: Mapped[Tenant] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.timestamp.asc()",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    from_me: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    conversation: Mapped[Conversation | None] = relationship(back_populates="messages")
    tenant: Mapped[Tenant] = relationship(back_populates="messages")
