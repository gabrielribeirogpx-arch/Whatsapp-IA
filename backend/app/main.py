from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine

from app import models  # noqa

from app.routers import webhook
from app.routers import chat
from app.routers import auth
from app.routers import products
from app.routers import knowledge
from app.routers import leads

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
app.include_router(chat.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(leads.router, prefix="/api")

# webhook normalmente externo (Meta)
app.include_router(webhook.router)

# ✅ STARTUP
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# ✅ HEALTH CHECK
@app.get("/")
def root():
    return {"status": "ok"}