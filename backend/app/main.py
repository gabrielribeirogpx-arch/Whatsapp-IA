from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.database import Base, engine
from backend.app import models  # noqa: F401
from backend.app.routers import webhook
from backend.app.routers import chat
from backend.app.routers import auth

app = FastAPI()

origins = [
    "http://localhost:3000",
    "https://whatsapp-ia-three.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(chat.router)
app.include_router(auth.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"status": "ok"}
