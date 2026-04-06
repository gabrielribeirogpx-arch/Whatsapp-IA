from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from backend.app.database import Base, engine
from backend.app.routers.chat import router as chat_router
from backend.app.routers.internal_api import router as internal_router
from backend.app.routers.webhook import router as webhook_router

Base.metadata.create_all(bind=engine)


def _run_lightweight_migrations() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "tenants" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE tenants (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(150) NOT NULL,
                        slug VARCHAR(80) UNIQUE,
                        phone_number_id VARCHAR(64) UNIQUE,
                        verify_token VARCHAR(255),
                        whatsapp_token VARCHAR(512),
                        plan VARCHAR(32) DEFAULT 'starter',
                        max_monthly_messages INTEGER DEFAULT 1000,
                        usage_month VARCHAR(7),
                        messages_used_month INTEGER DEFAULT 0,
                        is_blocked BOOLEAN DEFAULT 0,
                        admin_password VARCHAR(255) DEFAULT 'admin123',
                        created_at DATETIME
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO tenants (name, slug, phone_number_id, plan, max_monthly_messages, usage_month, messages_used_month, is_blocked, admin_password, created_at)
                    VALUES ('Tenant Default', 'default', 'default-phone-id', 'starter', 1000, strftime('%Y-%m', 'now'), 0, 0, 'admin123', CURRENT_TIMESTAMP)
                    """
                )
            )

        if "ai_config" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE ai_config (
                        id INTEGER PRIMARY KEY,
                        tenant_id INTEGER UNIQUE,
                        system_prompt TEXT,
                        model VARCHAR(64) DEFAULT 'gpt-4o-mini',
                        temperature FLOAT DEFAULT 0.4,
                        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                    )
                    """
                )
            )

        if "tenants" in tables:
            tenant_columns = {column["name"] for column in inspector.get_columns("tenants")}
            if "verify_token" not in tenant_columns:
                connection.execute(text("ALTER TABLE tenants ADD COLUMN verify_token VARCHAR(255)"))

        if "conversations" in tables:
            columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "tenant_id" not in columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN tenant_id INTEGER DEFAULT 1"))
            if "status" not in columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN status VARCHAR(16) DEFAULT 'bot'"))
                connection.execute(text("UPDATE conversations SET status='bot' WHERE status IS NULL OR status=''"))
            if "updated_at" not in columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN updated_at DATETIME"))
                connection.execute(text("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

        if "messages" in tables:
            msg_columns = {column["name"] for column in inspector.get_columns("messages")}
            if "tenant_id" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN tenant_id INTEGER DEFAULT 1"))
            if "conversation_id" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN conversation_id INTEGER"))
            if "role" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN role VARCHAR(16)"))
                connection.execute(text("UPDATE messages SET role=CASE WHEN from_me=1 THEN 'assistant' ELSE 'user' END WHERE role IS NULL"))
            if "message" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN message TEXT"))
                connection.execute(text("UPDATE messages SET message=content WHERE message IS NULL"))
            if "created_at" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN created_at DATETIME"))
                connection.execute(text("UPDATE messages SET created_at=timestamp WHERE created_at IS NULL"))

        if "conversations" in tables and "messages" in tables:
            connection.execute(
                text(
                    """
                    UPDATE messages
                    SET conversation_id = (
                        SELECT conversations.id
                        FROM conversations
                        WHERE conversations.phone = messages.phone
                          AND conversations.tenant_id = messages.tenant_id
                    )
                    WHERE conversation_id IS NULL
                    """
                )
            )

        connection.execute(
            text(
                """
                INSERT INTO ai_config (tenant_id, system_prompt, model, temperature)
                SELECT id,
                       'Você é um atendente profissional de WhatsApp para uma empresa de tecnologia. Responda de forma objetiva e cordial.',
                       'gpt-4o-mini',
                       0.4
                FROM tenants t
                WHERE NOT EXISTS (SELECT 1 FROM ai_config cfg WHERE cfg.tenant_id = t.id)
                """
            )
        )


_run_lightweight_migrations()

app = FastAPI(title="WhatsApp SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(chat_router)
app.include_router(internal_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}
