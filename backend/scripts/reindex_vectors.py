from __future__ import annotations

import argparse
import logging
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.flow_ai_long_term_memory import FlowAILongTermMemory
from app.models.knowledge_chunk import KnowledgeChunk
from app.services.vector_store_service import VectorStoreService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely reindex document and long-term memory vectors.")
    parser.add_argument("--tenant-id")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--documents", action="store_true")
    parser.add_argument("--memories", action="store_true")
    args = parser.parse_args()
    tenant_id = uuid.UUID(args.tenant_id) if args.tenant_id else None
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    processed = 0
    with SessionLocal() as db:
        service = VectorStoreService(db)
        logger.info("event=vector_reindex_started tenant_id=%s backend=%s dry_run=%s", tenant_id, service.get_backend(), args.dry_run)
        if args.documents or not args.memories:
            stmt = select(KnowledgeChunk).order_by(KnowledgeChunk.updated_at.desc() if hasattr(KnowledgeChunk, "updated_at") else KnowledgeChunk.created_at.desc()).limit(args.batch_size)
            if tenant_id:
                stmt = stmt.where(KnowledgeChunk.tenant_id == tenant_id)
            for row in db.execute(stmt).scalars():
                processed += 1
                if not args.dry_run:
                    service.upsert_embedding(tenant_id=row.tenant_id, namespace="document", object_id=row.id, content_text=row.content, embedding=row.embedding_json, metadata=row.metadata_json or {})
        if args.memories or not args.documents:
            stmt = select(FlowAILongTermMemory).order_by(FlowAILongTermMemory.updated_at.desc()).limit(args.batch_size)
            if tenant_id:
                stmt = stmt.where(FlowAILongTermMemory.tenant_id == tenant_id)
            for row in db.execute(stmt).scalars():
                processed += 1
                if not args.dry_run:
                    service.upsert_embedding(tenant_id=row.tenant_id, namespace="memory", object_id=row.id, content_text=row.fact_text, embedding=row.fact_embedding_json, metadata=row.metadata_json or {}, importance_score=float(row.importance_score or 0))
        if not args.dry_run:
            db.commit()
    logger.info("event=vector_reindex_completed tenant_id=%s processed=%s dry_run=%s", tenant_id, processed, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
