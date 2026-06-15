from uuid import UUID, uuid4
from pathlib import Path
import os
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import KnowledgeChunk, KnowledgeSource, Tenant
from app.schemas.knowledge import KnowledgeSourceOut, KnowledgeUploadOut
from app.services.rag_service import ingest_knowledge_source
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
ALLOWED_MIME_TYPES = {"application/pdf": "pdf", "text/plain": "text"}
MAX_UPLOAD_BYTES = int(os.getenv("KNOWLEDGE_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
STORAGE_ROOT = Path(os.getenv("KNOWLEDGE_STORAGE_DIR", "/data/knowledge"))


def _safe_filename(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "documento")[:180]
    return name or "documento"


@router.post("/upload", response_model=KnowledgeUploadOut)
async def upload_knowledge(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite configurado")
    mime_type = file.content_type or "application/octet-stream"
    source_type = ALLOWED_MIME_TYPES.get(mime_type)
    if not source_type and file.filename and file.filename.lower().endswith(".pdf"):
        source_type = "pdf"; mime_type = "application/pdf"
    if not source_type and file.filename and file.filename.lower().endswith(".txt"):
        source_type = "text"; mime_type = "text/plain"
    if not source_type:
        raise HTTPException(status_code=400, detail="Tipo de arquivo não suportado. Envie PDF ou TXT.")

    safe_name = _safe_filename(file.filename or "documento")
    tenant_dir = STORAGE_ROOT / str(tenant.id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    storage_path = tenant_dir / f"{uuid4()}_{safe_name}"
    storage_path.write_bytes(content)

    source = KnowledgeSource(tenant_id=tenant.id, name=safe_name, type=source_type, status="processing", original_filename=file.filename, mime_type=mime_type, size_bytes=len(content), storage_url=str(storage_path), metadata_json={})
    db.add(source)
    db.commit(); db.refresh(source)
    try:
        chunks_created = ingest_knowledge_source(db, tenant_id=tenant.id, source=source, raw_bytes=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Falha ao processar base de conhecimento") from exc
    return KnowledgeUploadOut(source=safe_name, source_id=source.id, status=source.status, chunks_created=chunks_created)


@router.get("/sources", response_model=list[KnowledgeSourceOut])
def list_sources(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    chunk_counts = dict(db.execute(select(KnowledgeChunk.source_id, func.count(KnowledgeChunk.id)).where(KnowledgeChunk.tenant_id == tenant.id).group_by(KnowledgeChunk.source_id)).all())
    sources = db.execute(select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant.id).order_by(KnowledgeSource.created_at.desc())).scalars().all()
    return [KnowledgeSourceOut.model_validate(src, from_attributes=True).model_copy(update={"chunks_count": int(chunk_counts.get(src.id, 0))}) for src in sources]


@router.get("/sources/{source_id}", response_model=KnowledgeSourceOut)
def get_source(source_id: UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    source = db.execute(select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == tenant.id)).scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    chunks_count = db.scalar(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.tenant_id == tenant.id, KnowledgeChunk.source_id == source.id)) or 0
    return KnowledgeSourceOut.model_validate(source, from_attributes=True).model_copy(update={"chunks_count": int(chunks_count)})


@router.delete("/sources/{source_id}")
def delete_source(source_id: UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    source = db.execute(select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == tenant.id)).scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    storage_url = source.storage_url
    db.delete(source); db.commit()
    if storage_url:
        try:
            Path(storage_url).unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True}

# Compatibilidade: a página antiga pode chamar /api/knowledge.
@router.get("", response_model=list[KnowledgeSourceOut])
def list_knowledge_alias(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return list_sources(tenant=tenant, db=db)
