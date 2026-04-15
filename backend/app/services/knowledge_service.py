import uuid
import re
from dataclasses import dataclass
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session
from PyPDF2 import PdfReader

from backend.app.models import KnowledgeBase, KnowledgeChunk
from backend.app.services.embedding_service import cosine_similarity, generate_embedding

SIMILARITY_THRESHOLD = 0.2
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


@dataclass
class RetrievedKnowledge:
    source: str
    content: str


def create_knowledge_item(db: Session, tenant_id: uuid.UUID, title: str, content: str) -> KnowledgeBase:
    item = KnowledgeBase(
        tenant_id=tenant_id,
        title=title.strip(),
        content=content.strip(),
        embedding=generate_embedding(content),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_knowledge_items(db: Session, tenant_id: uuid.UUID) -> list[KnowledgeBase]:
    return (
        db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        )
        .scalars()
        .all()
    )


def delete_knowledge_item(db: Session, tenant_id: uuid.UUID, knowledge_id: uuid.UUID) -> bool:
    item = (
        db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        .scalars()
        .first()
    )
    if not item:
        return False

    db.delete(item)
    db.commit()
    return True


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    content_parts: list[str] = []
    for page in reader.pages:
        content_parts.append(page.extract_text() or "")
    return clean_text("\n".join(content_parts))


def clean_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return normalized.strip()


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(cleaned):
        chunk = cleaned[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def process_pdf_knowledge(db: Session, tenant_id: uuid.UUID, source: str, pdf_bytes: bytes) -> int:
    pdf_text = extract_pdf_text(pdf_bytes)
    chunks = split_text_into_chunks(pdf_text)
    if not chunks:
        return 0

    created = 0
    for chunk in chunks:
        db.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                source=source,
                content=chunk,
                embedding=generate_embedding(chunk),
            )
        )
        created += 1

    db.commit()
    return created


def search_relevant_knowledge(db: Session, tenant_id: uuid.UUID, query_text: str, top_k: int = 5) -> list[RetrievedKnowledge]:
    query_embedding = generate_embedding(query_text)
    if not query_embedding:
        return []

    chunk_items = (
        db.execute(select(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    ranked_chunks = sorted(chunk_items, key=lambda item: cosine_similarity(item.embedding, query_embedding), reverse=True)

    relevant: list[RetrievedKnowledge] = []
    for item in ranked_chunks:
        score = cosine_similarity(item.embedding, query_embedding)
        if score < SIMILARITY_THRESHOLD:
            continue
        relevant.append(RetrievedKnowledge(source=item.source, content=item.content))
        if len(relevant) >= top_k:
            break

    if len(relevant) < top_k:
        legacy_items = (
            db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        ranked_legacy = sorted(legacy_items, key=lambda item: cosine_similarity(item.embedding, query_embedding), reverse=True)
        for item in ranked_legacy:
            score = cosine_similarity(item.embedding, query_embedding)
            if score < SIMILARITY_THRESHOLD:
                continue
            relevant.append(RetrievedKnowledge(source=item.title, content=item.content))
            if len(relevant) >= top_k:
                break
    return relevant


def build_rag_context(query_text: str, items: list[RetrievedKnowledge]) -> str:
    if not items:
        return query_text

    context_lines = ["Use essas informações para responder:"]
    for index, item in enumerate(items, start=1):
        context_lines.extend(
            [
                "",
                f"[CHUNK {index} - {item.source}]",
                item.content,
            ]
        )
    context_lines.extend(
        [
            "",
            f"Pergunta do cliente: {query_text}",
        ]
    )
    return "\n".join(context_lines)
