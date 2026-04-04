from fastapi import FastAPI, Request

app = FastAPI(title="WhatsApp SaaS API")


def process_message(data: dict):
    entries = data.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                text = message.get("text", {}).get("body")
                if text:
                    print(text)


@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    process_message(payload)
    return {"status": "received"}
