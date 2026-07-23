from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
import logging
import os

from sqlalchemy import text

from app.db.session import engine
from app.core.startup_checks import (
    is_production,
    run_migrations_if_enabled,
    validate_oauth_encryption_key,
    verify_alembic_at_head,
    verify_required_dependencies,
    verify_runtime_secrets,
    verify_oauth_redirect_uris,
    wait_for_database,
)

import app.models  # noqa: F401

from app.routers import webhook
from app.routers import chat as conversations
from app.routers import auth
from app.routers import products
from app.routers import knowledge
from app.routers import leads
from app.routers import dashboard
from app.routers import tasks
from app.routers import settings
from app.routers import account
from app.routers import ai_settings
from app.routers import ai_executions
from app.routers import ai_memories
from app.routers import mcp
from app.routers import bot_rules
from app.routers import flows
from app.routers import flow_media
from app.routers import whatsapp_providers, whatsapp_templates, whatsapp_campaigns
from app.routers import admin_investigation
from app.routers import admin_conversation_reset
from app.routers import observability
from app.routers import integration_connections, google_calendar_integration, gmail_integration, google_drive_integration, google_sheets_integration, suitable_integration, meta_integration
from app.routers import billing
from app.middleware.tenant_context import TenantContextMiddleware
from app.api.debug import router as debug_router
from app.api.flow_runtime import router as flow_runtime_router
from app.api.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.flow_execute import router as flow_execute_router
from app.api.whatsapp import router as whatsapp_router
from app.api.runtime_health import router as runtime_health_router
from app.api.runtime_metrics import router as runtime_metrics_router
from app.api.runtime_flow_debug import router as runtime_flow_debug_router
from app.api.debugger import router as debugger_router


logger = logging.getLogger(__name__)

def verify_contacts_columns() -> None:
    required_columns = {
        "tags_json",
        "custom_fields_json",
        "first_name",
        "last_name",
    }
    try:
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'contacts'
                    """
                )
            ).fetchall()
        existing_columns = {row[0] for row in rows}
        missing = sorted(required_columns - existing_columns)
        if missing:
            logger.warning("event=db_check_contacts_missing_columns missing=%s", missing)
        else:
            logger.info("event=db_check_contacts_columns_verified")
    except Exception as exc:
        logger.warning("event=db_check_contacts_verification_failed error=%s", type(exc).__name__)


REQUIRED_CORS_ORIGINS = (
    "https://app.wazzaapi.com.br",
    "https://api.wazzaapi.com.br",
)

DEFAULT_CORS_ORIGINS = (
    *REQUIRED_CORS_ORIGINS,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def _parse_allowed_origins() -> list[str]:
    configured_origins = (
        os.getenv("CORS_ORIGINS")
        or os.getenv("CORS_ALLOW_ORIGINS")
    )
    candidate_origins = (
        [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
        if configured_origins
        else list(DEFAULT_CORS_ORIGINS)
    )

    parsed: list[str] = []
    for origin in [*candidate_origins, *REQUIRED_CORS_ORIGINS]:
        if origin not in parsed:
            parsed.append(origin)
    return parsed


def _parse_allowed_origin_regex() -> str | None:
    regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip()
    return regex or None


ALLOWED_ORIGINS = _parse_allowed_origins()
ALLOWED_ORIGIN_REGEX = _parse_allowed_origin_regex()

app = FastAPI()

app.include_router(flow_media.public_router)
app.include_router(mcp.router)
app.mount("/uploads", StaticFiles(directory=os.getenv("FLOW_MEDIA_STATIC_DIR", "/data/uploads"), check_dir=False), name="uploads")

app.add_middleware(TenantContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
)



@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.info("event=request_validation_failed path=%s", request.url.path)
    if request.url.path == "/api/register":
        first_error = exc.errors()[0] if exc.errors() else {}
        location = first_error.get("loc", [])
        field = location[-1] if location and isinstance(location[-1], str) else None
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": {"code": "VALIDATION_ERROR", "field": field, "message": "Revise o campo informado e tente novamente."}},
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# ✅ STARTUP (CORRETO)
@app.on_event("startup")
def on_startup():
    logger.info("event=startup production=%s", is_production())
    verify_required_dependencies()
    verify_runtime_secrets()
    validate_oauth_encryption_key()
    verify_oauth_redirect_uris()
    wait_for_database()
    flow_media.log_upload_storage_status()
    run_migrations_if_enabled()
    verify_alembic_at_head()
    verify_contacts_columns()


@app.options("/{path:path}")
async def options_handler(path: str):
    return Response(status_code=204)


# Compatibilidade com testes e imports legados que ainda usam o nome antigo.
preflight_handler = options_handler


# ✅ ROUTES
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(conversations.router, prefix="/api/api")
app.include_router(products.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(ai_settings.router, prefix="/api")
app.include_router(ai_executions.router, prefix="/api")
app.include_router(ai_memories.router, prefix="/api")
app.include_router(bot_rules.router)
app.include_router(flows.crud_router, prefix="/api/flows", tags=["flows"])
app.include_router(flow_media.router)
app.include_router(flow_media.media_router)
app.include_router(flows.router, prefix="/api/admin", tags=["admin"])
app.include_router(whatsapp_providers.router)
app.include_router(
    whatsapp_templates.router,
    prefix="/api/whatsapp/templates",
    tags=["WhatsApp Templates"],
)
app.include_router(whatsapp_campaigns.router)
app.include_router(admin_investigation.router)
app.include_router(admin_conversation_reset.router)
app.include_router(observability.router, prefix="/api")
app.include_router(integration_connections.router, prefix="/api")
app.include_router(google_calendar_integration.router, prefix="/api")
app.include_router(gmail_integration.router, prefix="/api")
app.include_router(google_drive_integration.router, prefix="/api")
app.include_router(google_sheets_integration.router, prefix="/api")
app.include_router(suitable_integration.router)
app.include_router(meta_integration.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(billing.admin_router, prefix="/api")
# Webhooks ativos:
# - Canônico (Meta): /webhook (sem prefixo), via app.routers.webhook
# - Compatibilidade legada: /api/webhook/whatsapp, via app.api.whatsapp_webhook
app.include_router(webhook.router)
app.include_router(debug_router)
app.include_router(flow_runtime_router, prefix="/api")
app.include_router(flow_execute_router, prefix="/api")
app.include_router(whatsapp_webhook_router, prefix="/api")
app.include_router(whatsapp_router, prefix="/api")
app.include_router(runtime_health_router, prefix="/api")
app.include_router(runtime_metrics_router, prefix="/api")
app.include_router(runtime_flow_debug_router)
app.include_router(debugger_router)


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
