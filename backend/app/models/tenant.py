from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.product import Product
from app.models.bot_rule import BotRule

DEFAULT_SYSTEM_PROMPT = "Você é um assistente de vendas altamente persuasivo, especializado em converter leads em clientes."


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("ai_mode IN ('atendente', 'vendedor')", name="ck_tenants_ai_mode"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    ai_mode: Mapped[str] = mapped_column(String(32), default="atendente", server_default="atendente")

    ai_config: Mapped["AIConfig | None"] = relationship(back_populates="tenant", uselist=False, cascade="all, delete-orphan")
    products: Mapped[list[Product]] = relationship(Product, back_populates="tenant", cascade="all, delete-orphan")
    knowledge_items: Mapped[list[KnowledgeBase]] = relationship(
        KnowledgeBase,
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    knowledge_chunks: Mapped[list[KnowledgeChunk]] = relationship(
        KnowledgeChunk,
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    bot_rules: Mapped[list[BotRule]] = relationship(BotRule, back_populates="tenant", cascade="all, delete-orphan")


class AIConfig(Base):
    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True)
    system_prompt: Mapped[str] = mapped_column(Text, default=DEFAULT_SYSTEM_PROMPT)
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, default=0.4)

    tenant: Mapped[Tenant] = relationship(back_populates="ai_config")
