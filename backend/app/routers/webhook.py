from fastapi import APIRouter, Request

from backend.app.services.whatsapp_service import send_whatsapp_message

router = APIRouter()


@router.get("/webhook")
async def verify():
    return {"status": "webhook ativo"}


@router.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
        print("Payload recebido:", payload)

        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        phone = message["from"]
        incoming_message = message.get("text", {}).get("body", "")

        print(f"Mensagem recebida de {phone}: {incoming_message}")

        send_whatsapp_message(phone, "🔥 Olá! Aqui é a IA. Como posso te ajudar?")
        print(f"Resposta automática enviada para {phone}")
    except Exception as e:
        print("Erro ao processar webhook:", str(e))

    return {"status": "message processed"}
