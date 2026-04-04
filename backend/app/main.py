from fastapi import FastAPI

app = FastAPI(title="WhatsApp SaaS API")

@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}