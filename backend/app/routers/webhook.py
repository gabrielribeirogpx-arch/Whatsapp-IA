from fastapi import APIRouter, Request

from backend.app.services.message_service import process_message

router = APIRouter(tags=["webhook"])


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    responses = process_message(payload)
    return {"status": "received", "responses": responses}
