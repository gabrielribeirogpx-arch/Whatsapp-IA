import sys
import time
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db.base import Base
from backend.app.db.session import engine
from backend.app import models  # noqa: F401
from backend.app.routers import webhook
from backend.app.routers import chat
from backend.app.routers import auth
from backend.app.routers import products
from backend.app.routers import knowledge
from backend.app.routers import leads

print("🚀 APP STARTED - DEBUG MODE")


def handle_exception(exc_type, exc_value, exc_traceback):
    print("🔥 EXCEPTION GLOBAL:")
    traceback.print_exception(exc_type, exc_value, exc_traceback)


sys.excepthook = handle_exception

app = FastAPI()
START_TIME = time.monotonic()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print("🔥 ERRO GLOBAL:")
        print(str(e))
        traceback.print_exc()
        raise e


app.include_router(webhook.router)
app.include_router(chat.router)
app.include_router(auth.router, prefix="/api")
app.include_router(products.router)
app.include_router(knowledge.router)
app.include_router(leads.router)


@app.on_event("startup")
def on_startup() -> None:
    print("🔥 STARTUP EVENT EXECUTADO")
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"status": "ok"}


@app.on_event("startup")
async def test_db() -> None:
    try:
        from backend.app.core.database import engine as core_engine

        conn = core_engine.connect()
        print("✅ DB CONNECTED")
        conn.close()
    except Exception as e:
        print("💣 DB ERROR NO STARTUP:", str(e))


@app.on_event("shutdown")
async def shutdown_event() -> None:
    print("💀 SHUTDOWN EVENT EXECUTADO")


@app.get("/health")
def health():
    return {"status": "ok", "uptime_seconds": round(time.monotonic() - START_TIME, 2)}
