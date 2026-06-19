from __future__ import annotations

import logging, os, re, uuid
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.flow_ai_long_term_memory import FlowAILongTermMemory
from app.services.vector_backend import JsonEmbeddingBackend
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)
ALLOWED_FACT_TYPES = {'custom','identity','contact','company','preference','product_interest','note'}
# TODO: política de retenção por tenant para expurgo/LGPD.
# TODO: exportação de dados do contato.
# TODO: consentimento explícito para memória longa por tenant/contato.
SECRET_RE = re.compile(r'(api[_-]?key|token|secret|senha|password|authorization|bearer\s+[a-z0-9._-]+)', re.I)


def _enabled() -> bool: return os.getenv('AI_LONG_TERM_MEMORY_ENABLED', 'true').lower() in {'1','true','yes','on'}
def _uuid(v):
    if v in (None, ''): return None
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
def _safe_fact(text: str) -> str:
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not text or len(text) > 1000 or SECRET_RE.search(text): return ''
    return text

def _serialize(row: FlowAILongTermMemory, score: float | None = None) -> dict[str, Any]:
    metadata = dict(row.metadata_json or {})
    sensitive = metadata.get('sensitive') is True
    fact_text = '[dado sensível oculto]' if sensitive else row.fact_text
    return {'id': str(row.id), 'tenant_id': str(row.tenant_id), 'contact_id': str(row.contact_id) if row.contact_id else None,
            'conversation_id': str(row.conversation_id) if row.conversation_id else None, 'session_id': str(row.session_id) if row.session_id else None,
            'fact_text': fact_text, 'fact_type': row.fact_type, 'importance_score': float(row.importance_score or 0), 'source': row.source,
            'expires_at': row.expires_at.isoformat() if row.expires_at else None, 'metadata': metadata, 'created_at': row.created_at.isoformat() if row.created_at else None,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None, 'score': score, 'has_embedding': bool(row.fact_embedding_json)}


def store_fact(db: Session, tenant_id, contact_id, fact_text: str, fact_type='custom', importance_score=0.5, conversation_id=None, session_id=None, source=None, metadata=None):
    if not _enabled(): return None
    tenant_id, contact_id = _uuid(tenant_id), _uuid(contact_id)
    if tenant_id is None or contact_id is None: return None
    fact = _safe_fact(fact_text)
    if not fact: return None
    fact_type = fact_type if fact_type in ALLOWED_FACT_TYPES else 'custom'
    existing = db.execute(select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id==tenant_id, FlowAILongTermMemory.contact_id==contact_id, FlowAILongTermMemory.fact_type==fact_type, FlowAILongTermMemory.fact_text.ilike(fact[:120]))).scalars().first()
    if existing: return existing
    embedding = None
    try: embedding = JsonEmbeddingBackend(db).embed_text(tenant_id, fact)
    except Exception as exc: logger.warning('[AI LTM] embedding_failed tenant_id=%s contact_id=%s error=%s', tenant_id, contact_id, type(exc).__name__)
    row = FlowAILongTermMemory(tenant_id=tenant_id, contact_id=contact_id, conversation_id=_uuid(conversation_id), session_id=_uuid(session_id), fact_text=fact, fact_embedding_json=embedding, fact_type=fact_type, importance_score=max(0, min(float(importance_score or 0.5), 1)), source=str(source)[:120] if source else None, metadata_json=dict(metadata or {}))
    db.add(row); db.flush()
    try:
        VectorStoreService(db).upsert_embedding(tenant_id=tenant_id, namespace="memory", object_id=row.id, content_text=fact, embedding=embedding, metadata={**dict(metadata or {}), "memory_type": fact_type}, importance_score=float(row.importance_score or 0))
    except Exception as exc:
        logger.warning('event=vector_store_error tenant_id=%s backend=unknown error_code=%s', tenant_id, type(exc).__name__)
    return row


def search_memory(db: Session, tenant_id, contact_id, query: str, top_k=5, min_similarity=0.25, fact_types=None):
    if not _enabled() or not contact_id: return []
    tenant_id, contact_id = _uuid(tenant_id), _uuid(contact_id)
    stmt = select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id==tenant_id, FlowAILongTermMemory.contact_id==contact_id, or_(FlowAILongTermMemory.expires_at.is_(None), FlowAILongTermMemory.expires_at > datetime.now(UTC).replace(tzinfo=None)))
    if fact_types: stmt = stmt.where(FlowAILongTermMemory.fact_type.in_([t for t in fact_types if t in ALLOWED_FACT_TYPES]))
    rows = db.execute(stmt.order_by(FlowAILongTermMemory.created_at.desc()).limit(200)).scalars().all()
    if not rows: return []
    try:
        vector_results = VectorStoreService(db).search_similar(tenant_id=tenant_id, namespace="memory", query_text=query or '', top_k=top_k, filters={"contact_id": contact_id}, min_score=float(min_similarity))
        by_id = {str(r.id): r for r in rows}
        scored = []
        for item in vector_results:
            row = by_id.get(str(item.get("memory_id") or item.get("id")))
            if row:
                scored.append((_serialize(row, float(item.get("score") or 0)), float(item.get("score") or 0)))
        if scored:
            return [x for x,_ in sorted(scored, key=lambda p:p[1], reverse=True)[:max(1,int(top_k or 5))]]
    except Exception as exc:
        logger.warning('event=vector_store_fallback tenant_id=%s backend=unknown error_code=%s', tenant_id, type(exc).__name__)
    backend = JsonEmbeddingBackend(db); q_emb = None
    try: q_emb = backend.embed_text(tenant_id, query or '') if query else None
    except Exception as exc: logger.warning('[AI LTM] query_embedding_failed tenant_id=%s contact_id=%s error=%s', tenant_id, contact_id, type(exc).__name__)
    scored=[]
    terms = {t.lower() for t in re.findall(r'\w{3,}', str(query or ''))}
    for r in rows:
        score = backend.similarity(q_emb, r.fact_embedding_json) if q_emb and r.fact_embedding_json else (0.4 if terms & set(re.findall(r'\w{3,}', r.fact_text.lower())) else 0.0)
        if score >= float(min_similarity): scored.append((_serialize(r, score), score))
    return [x for x,_ in sorted(scored, key=lambda p:p[1], reverse=True)[:max(1,int(top_k or 5))]]


def list_memories(db: Session, tenant_id, contact_id=None, query=None, fact_type=None, limit=50, offset=0):
    stmt=select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id==_uuid(tenant_id))
    if contact_id: stmt=stmt.where(FlowAILongTermMemory.contact_id==_uuid(contact_id))
    if fact_type: stmt=stmt.where(FlowAILongTermMemory.fact_type==fact_type)
    if query: stmt=stmt.where(FlowAILongTermMemory.fact_text.ilike(f'%{str(query)[:120]}%'))
    rows=db.execute(stmt.order_by(FlowAILongTermMemory.created_at.desc()).offset(max(0,int(offset or 0))).limit(min(max(1,int(limit or 50)),100))).scalars().all()
    return [_serialize(r) for r in rows]

def update_fact(db: Session, tenant_id, memory_id, fact_text=None, fact_type=None, importance_score=None, expires_at=None, metadata=None):
    row=db.execute(select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id==_uuid(tenant_id), FlowAILongTermMemory.id==_uuid(memory_id))).scalars().first()
    if not row: return None
    if fact_text is not None:
        safe=_safe_fact(fact_text)
        if safe: row.fact_text=safe; row.fact_embedding_json=None
    if fact_type is not None: row.fact_type=fact_type if fact_type in ALLOWED_FACT_TYPES else 'custom'
    if importance_score is not None: row.importance_score=max(0,min(float(importance_score),1))
    if expires_at is not None: row.expires_at=expires_at
    if metadata is not None: row.metadata_json=dict(metadata or {})
    row.updated_at=datetime.utcnow(); db.add(row); db.flush(); return row

def delete_fact(db: Session, tenant_id, memory_id) -> bool:
    row=db.execute(select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id==_uuid(tenant_id), FlowAILongTermMemory.id==_uuid(memory_id))).scalars().first()
    if not row: return False
    db.delete(row); db.flush(); return True
