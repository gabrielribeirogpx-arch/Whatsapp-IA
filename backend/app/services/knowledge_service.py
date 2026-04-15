import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeBase
from backend.app.services.embedding_service import cosine_similarity, generate_embedding

SIMILARITY_THRESHOLD = 0.2


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


def search_relevant_knowledge(db: Session, tenant_id: uuid.UUID, query_text: str, top_k: int = 3) -> list[KnowledgeBase]:
    query_embedding = generate_embedding(query_text)
    if not query_embedding:
        return []

    items = (
        db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    ranked = sorted(
        items,
        key=lambda item: cosine_similarity(item.embedding, query_embedding),
        reverse=True,
    )

    relevant: list[KnowledgeBase] = []
    for item in ranked:
        if cosine_similarity(item.embedding, query_embedding) < SIMILARITY_THRESHOLD:
            continue
        relevant.append(item)
        if len(relevant) >= top_k:
            break
    return relevant


def build_rag_context(query_text: str, items: list[KnowledgeBase]) -> str:
    if not items:
        return query_text

    context_lines = ["Use as informações abaixo para responder:"]
    for index, item in enumerate(items, start=1):
        context_lines.extend(
            [
                "",
                f"[CONTEÚDO {index} - {item.title}]",
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
