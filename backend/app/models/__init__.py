from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message


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
    is_blocked: Mapped[bool] = mapped_column(default=False)
    admin_password: Mapped[str] = mapped_column(String(255), default="admin123")

    ai_config: Mapped["AIConfig | None"] = relationship(back_populates="tenant", uselist=False, cascade="all, delete-orphan")


class AIConfig(Base):
    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, default=0.4)

    tenant: Mapped[Tenant] = relationship(back_populates="ai_config")


__all__ = ["Tenant", "AIConfig", "Conversation", "Message"]
