from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI()

# ✅ CORS CORRETO PARA VERCEL + LOCAL
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://whatsapp-ia-three.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # ⚠️ NÃO usa "*" em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ ROTAS COM PREFIXO PADRÃO /api
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(conversations.router, prefix="/api/api")  # backward compatibility
app.include_router(products.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")

# webhook normalmente externo (Meta)
app.include_router(webhook.router)

# ✅ STARTUP
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# ✅ HEALTH CHECK
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"status": "ok"}
