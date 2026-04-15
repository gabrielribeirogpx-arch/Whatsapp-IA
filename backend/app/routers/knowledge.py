from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Tenant
from backend.app.schemas.knowledge import KnowledgeCreate, KnowledgeOut
from backend.app.services.knowledge_service import create_knowledge_item, delete_knowledge_item, list_knowledge_items
from backend.app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("", response_model=KnowledgeOut)
def create_knowledge(
    payload: KnowledgeCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return create_knowledge_item(db=db, tenant_id=tenant.id, title=payload.title, content=payload.content)


@router.get("", response_model=list[KnowledgeOut])
def list_knowledge(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return list_knowledge_items(db=db, tenant_id=tenant.id)


@router.delete("/{knowledge_id}")
def remove_knowledge(
    knowledge_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    deleted = delete_knowledge_item(db=db, tenant_id=tenant.id, knowledge_id=knowledge_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado")
    return {"deleted": True}
