from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from backend.app.database import Base, engine
from backend.app.routers.chat import router as chat_router
from backend.app.routers.webhook import router as webhook_router

Base.metadata.create_all(bind=engine)


def _run_lightweight_migrations() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "conversations" in tables:
            columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "status" not in columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN status VARCHAR(16) DEFAULT 'bot'"))
                connection.execute(text("UPDATE conversations SET status='human' WHERE lower(assigned_to)='humano'"))
                connection.execute(text("UPDATE conversations SET status='bot' WHERE status IS NULL OR status=''"))
            if "updated_at" not in columns:
                connection.execute(text("ALTER TABLE conversations ADD COLUMN updated_at DATETIME"))
                connection.execute(text("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

        if "messages" in tables:
            msg_columns = {column["name"] for column in inspector.get_columns("messages")}
            if "conversation_id" not in msg_columns:
                connection.execute(text("ALTER TABLE messages ADD COLUMN conversation_id INTEGER"))

        if "conversations" in tables and "messages" in tables:
            connection.execute(
                text(
                    """
                    UPDATE messages
                    SET conversation_id = (
                        SELECT conversations.id FROM conversations WHERE conversations.phone = messages.phone
                    )
                    WHERE conversation_id IS NULL
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


@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}
