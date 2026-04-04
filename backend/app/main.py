from fastapi import FastAPI, Request

app = FastAPI(title="WhatsApp SaaS API")

@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}

@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    print("Webhook recebido:", payload)
    return {"status": "received"}
