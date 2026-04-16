from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine
from app import models  # noqa: F401
from app.routers import webhook
from app.routers import chat
from app.routers import auth
from app.routers import products
from app.routers import knowledge
from app.routers import leads

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(chat.router)
app.include_router(auth.router, prefix="/api")
app.include_router(products.router)
app.include_router(knowledge.router)
app.include_router(leads.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"status": "ok"}
