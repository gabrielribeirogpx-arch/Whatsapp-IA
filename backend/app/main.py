from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from alembic.config import Config
from alembic import command
import os
from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine

import app.models  # noqa: F401

from app.routers import webhook
from app.routers import chat as conversations
from app.routers import auth
from app.routers import products
from app.routers import knowledge
from app.routers import leads
from app.routers import dashboard
from app.routers import settings
from app.routers import bot_rules
from app.routers import flows
from app.middleware.tenant_context import TenantContextMiddleware
from app.api.debug import router as debug_router
from app.api.flow_runtime import router as flow_runtime_router
from app.api.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.flow_execute import router as flow_execute_router
from app.api.whatsapp import router as whatsapp_router


# ✅ MIGRATIONS
def run_migrations():
    try:
        if os.getenv("RUN_MIGRATIONS", "true") == "true":
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")
            print("✅ Migrations aplicadas com sucesso")
    except Exception as e:
        print("❌ Erro ao rodar migrations:", e)


# ✅ SAFE ALTER TABLE
def ensure_conversations_columns():
    statements = [
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_bot_question TEXT;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_objective TEXT;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_bot_triggered_message_id UUID;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_intent TEXT;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS intent_history JSONB;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_intent_at TIMESTAMP;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS lead_score INTEGER DEFAULT 0;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_step TEXT;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_flow UUID;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_node_id UUID;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context JSONB;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_input TEXT;",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS retries INTEGER DEFAULT 0;",
        "ALTER TABLE flows ADD COLUMN IF NOT EXISTS published_version_id UUID;",
        "ALTER TABLE flows ADD COLUMN IF NOT EXISTS current_version_id UUID;",
        "ALTER TABLE flows ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;",
        "ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS tenant_id UUID;",
        "ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS snapshot JSONB;",
        "ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS nodes JSONB;",
        "ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS edges JSONB;",
        "ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false;",
    ]
    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        print("✅ Estrutura de conversations validada com SQL de segurança")
    except Exception as e:
        print("❌ Erro ao validar estrutura:", e)


def _parse_allowed_origins() -> list[str]:
    origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "https://whatsapp-ia-nine.vercel.app,http://localhost:3000",
    )
    parsed = [origin.strip() for origin in origins.split(",") if origin.strip()]
    return parsed or ["*"]


def _parse_allowed_origin_regex() -> str | None:
    regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip()
    return regex or None


ALLOWED_ORIGINS = _parse_allowed_origins()
ALLOWED_ORIGIN_REGEX = _parse_allowed_origin_regex()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("ERRO 422 DETALHADO:", exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# ✅ STARTUP (CORRETO)
@app.on_event("startup")
def on_startup():
    print(f"[CORS] enabled origins={ALLOWED_ORIGINS} origin_regex={ALLOWED_ORIGIN_REGEX}")
    run_migrations()
    Base.metadata.create_all(bind=engine)
    ensure_conversations_columns()


app.add_middleware(TenantContextMiddleware)


@app.options("/{path:path}")
async def options_handler(path: str):
    return Response(status_code=200)



# ✅ ROUTES
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(conversations.router, prefix="/api/api")
app.include_router(products.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(bot_rules.router)
app.include_router(flows.crud_router, prefix="/api/flows", tags=["flows"])
app.include_router(webhook.router)
app.include_router(debug_router)
app.include_router(flow_runtime_router, prefix="/api")
app.include_router(flow_execute_router, prefix="/api")
app.include_router(whatsapp_webhook_router, prefix="/api")
app.include_router(whatsapp_router, prefix="/api")


# ✅ HEALTH
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"status": "ok"}


# ✅ START SERVER (CRÍTICO)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
