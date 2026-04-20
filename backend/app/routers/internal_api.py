from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.chat import ConversationOut, MessageOut, SendMessageRequest
from app.services.tenant_service import get_current_tenant
from app.models import Tenant
from app.routers.chat import get_messages as get_messages_api
from app.routers.chat import list_conversations as list_conversations_api
from app.routers.chat import send_message as send_message_api

router = APIRouter(tags=["internal-api"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return list_conversations_api(tenant=tenant, db=db)


@router.get("/messages/{phone}", response_model=list[MessageOut])
def get_messages(
    phone: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return get_messages_api(phone=phone, tenant=tenant, db=db)


@router.post("/send-message", response_model=MessageOut)
async def send_message(
    payload: SendMessageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return await send_message_api(payload=payload, tenant=tenant, db=db)
