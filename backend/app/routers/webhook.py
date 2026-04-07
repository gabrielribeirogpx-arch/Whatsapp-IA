from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/webhook")
async def verify():
    return {"status": "webhook ativo"}


@router.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
        print("Payload:", payload)
    except Exception as e:
        print("Erro:", str(e))

    return {"status": "ok"}
