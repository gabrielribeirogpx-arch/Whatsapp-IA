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

        if "entry" not in payload:
            print("Evento ignorado: payload sem 'entry'")
            return {"status": "ignored"}

        entry = payload.get("entry", [])[0] if payload.get("entry") else {}
        changes = entry.get("changes", [])[0] if entry.get("changes") else {}
        value = changes.get("value", {})
        event_type = "messages" if "messages" in value else "other"

        if "messages" not in value:
            print(f"Evento recebido sem mensagens (tipo={event_type})")
            return {"status": "no messages event"}

        messages = value["messages"]
        if not messages:
            print(f"Evento recebido com lista de mensagens vazia (tipo={event_type})")
            return {"status": "no messages event"}

        message = messages[0]

        if "text" not in message:
            phone = message.get("from", "desconhecido")
            print(
                f"Evento não textual ignorado (tipo={event_type}, telefone={phone}, conteúdo=<sem texto>)"
            )
            return {"status": "non-text message ignored"}

        phone = message["from"]
        incoming_message = message.get("text", {}).get("body", "")

        print(
            f"Evento processado (tipo={event_type}, telefone={phone}, conteúdo={incoming_message})"
        )

        send_whatsapp_message(phone, "🔥 Olá! Aqui é a IA. Como posso te ajudar?")
        print(f"Resposta automática enviada para {phone}")
    except Exception as e:
        print("Erro ao processar webhook:", str(e))

    return {"status": "message processed"}
