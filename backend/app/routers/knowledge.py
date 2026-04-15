from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Tenant
from backend.app.schemas.knowledge import (
    KnowledgeCreate,
    KnowledgeCrawlOut,
    KnowledgeCrawlRequest,
    KnowledgeOut,
    KnowledgeUploadOut,
)
from backend.app.services.knowledge_service import (
    create_knowledge_item,
    delete_knowledge_item,
    list_knowledge_items,
    process_pdf_knowledge,
    process_site_knowledge,
)
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


@router.post("/upload-pdf", response_model=KnowledgeUploadOut)
async def upload_pdf_knowledge(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF válido")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    chunks_created = process_pdf_knowledge(
        db=db,
        tenant_id=tenant.id,
        source=file.filename,
        pdf_bytes=content,
    )
    if chunks_created == 0:
        raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF")

    return KnowledgeUploadOut(source=file.filename, chunks_created=chunks_created)


@router.post("/crawl", response_model=KnowledgeCrawlOut)
def crawl_knowledge_site(
    payload: KnowledgeCrawlRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    try:
        pages_collected, chunks_created = process_site_knowledge(
            db=db,
            tenant_id=tenant.id,
            url=payload.url,
            depth=payload.depth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if chunks_created == 0:
        raise HTTPException(status_code=400, detail="Nenhum conteúdo relevante foi encontrado no site")

    return KnowledgeCrawlOut(
        source=payload.url,
        pages_collected=pages_collected,
        chunks_created=chunks_created,
    )
