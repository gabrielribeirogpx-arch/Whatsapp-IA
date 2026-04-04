from fastapi import FastAPI, Request

app = FastAPI(title="WhatsApp SaaS API")


def generate_response(message: str) -> str:
    return "Recebi sua mensagem"


def process_message(data: dict):
    entries = data.get("entry", [])
    responses = []

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                text = message.get("text", {}).get("body")
                if text:
                    print(text)
                    response = generate_response(text)
                    print(response)
                    responses.append(response)

    return responses


@app.get("/")
def root():
    return {"status": "ok", "message": "API rodando 🚀"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    responses = process_message(payload)
    return {"status": "received", "responses": responses}
