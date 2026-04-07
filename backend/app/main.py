from fastapi import FastAPI

from backend.app.core.database import Base, engine
from backend.app import models  # noqa: F401
from backend.app.routers import webhook

app = FastAPI()

app.include_router(webhook.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"status": "ok"}
