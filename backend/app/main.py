from fastapi import FastAPI

from app.routers.webhook import router as webhook_router

app = FastAPI(title="WhatsApp SaaS API")

app.include_router(webhook_router)


@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}
