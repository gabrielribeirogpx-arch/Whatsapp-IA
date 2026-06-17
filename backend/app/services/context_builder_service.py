from __future__ import annotations

import logging, os, re, time
from typing import Any

from sqlalchemy.orm import Session

from app.services.flow_ai_memory_service import flow_ai_memory_service
from app.services.long_term_memory_service import search_memory, store_fact

logger = logging.getLogger(__name__)


def context_builder_enabled() -> bool:
    return os.getenv('AI_CONTEXT_BUILDER_ENABLED', 'true').lower() in {'1','true','yes','on'}


def build_context(db: Session, tenant_id, contact_id=None, conversation_id=None, session_id=None, current_query=None, include_short_memory=True, include_long_memory=True, include_rag_context=False, short_memory_options=None, long_memory_options=None, rag_options=None) -> dict[str, Any]:
    started=time.monotonic(); fallback=False
    history=[]; history_text=''; memories=[]; rag=[]
    try:
        if include_short_memory and session_id:
            opts=short_memory_options or {}
            history=flow_ai_memory_service.get_recent_history(db, tenant_id=tenant_id, session_id=session_id, max_messages=opts.get('max_messages',10), max_chars=opts.get('max_chars',4000))
            history_text=flow_ai_memory_service.build_history_for_prompt(history)
    except Exception as exc:
        fallback=True; logger.warning('[CONTEXT BUILDER] short_memory_failed tenant_id=%s session_id=%s error=%s', tenant_id, session_id, type(exc).__name__)
    try:
        if include_long_memory and contact_id:
            opts=long_memory_options or {}
            memories=search_memory(db, tenant_id, contact_id, current_query or '', top_k=opts.get('top_k',5), min_similarity=opts.get('min_similarity',0.25), fact_types=opts.get('fact_types'))
    except Exception as exc:
        fallback=True; logger.warning('[CONTEXT BUILDER] long_memory_failed tenant_id=%s contact_id=%s error=%s', tenant_id, contact_id, type(exc).__name__)
    try:
        if include_rag_context and rag_options:
            rag=list(rag_options.get('chunks') or rag_options.get('rag_context') or [])[:10]
    except Exception as exc:
        fallback=True; logger.warning('[CONTEXT BUILDER] rag_context_failed tenant_id=%s error=%s', tenant_id, type(exc).__name__)
    sections=[]
    if history_text: sections.append('=== HISTÓRICO RECENTE ===\n' + history_text[:4000])
    if memories: sections.append('=== MEMÓRIA DO CONTATO ===\n' + '\n'.join(f"- ({m.get('fact_type')}, score={float(m.get('score') or 0):.2f}) {m.get('fact_text')}" for m in memories)[:3000])
    if rag: sections.append('=== BASE DE CONHECIMENTO ===\n' + '\n'.join(str(c.get('content') if isinstance(c,dict) else c)[:1000] for c in rag)[:5000])
    return {'conversation_history': [{'role':getattr(h,'role',None),'content':getattr(h,'content','')} for h in history], 'long_term_memory': memories, 'rag_context': rag, 'combined_prompt_section': '\n\n'.join(sections), 'metadata': {'short_memory_count': len(history), 'long_memory_count': len(memories), 'rag_context_count': len(rag), 'memory_latency_ms': int((time.monotonic()-started)*1000), 'fallback_used': fallback}}

_PATTERNS=[(re.compile(r'\bmeu nome (?:é|e)\s+([^,.!\n]{2,80})', re.I),'identity','Nome: {v}'),(re.compile(r'\bminha empresa (?:é|e)\s+([^,.!\n]{2,100})', re.I),'company','Empresa: {v}'),(re.compile(r'\bprefiro\s+([^.!\n]{3,120})', re.I),'preference','Preferência: {v}'),(re.compile(r'\bmeu e-?mail (?:é|e)\s+([\w.%-]+@[\w.-]+\.[A-Za-z]{2,})', re.I),'contact','Email: {v}'),(re.compile(r'\btenho interesse (?:no|na|em|pelo|pela)\s+([^.!\n]{3,120})', re.I),'product_interest','Interesse: {v}')]

def extract_memories_from_message(db: Session, tenant_id, contact_id, message_text: str, conversation_history=None) -> list[dict[str, Any]]:
    if not contact_id or not message_text or len(str(message_text))>1200: return []
    saved=[]
    for regex, typ, tmpl in _PATTERNS:
        m=regex.search(str(message_text))
        if not m: continue
        value=re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(value)<2: continue
        sensitive = typ == 'contact'
        row=store_fact(db, tenant_id, contact_id, tmpl.format(v=value), fact_type=typ, importance_score=0.8, source='auto_extraction', metadata={'confidence':0.8, 'sensitive': sensitive} if sensitive else {'confidence':0.8})
        if row: saved.append({'id': str(row.id), 'fact_type': typ})
    return saved
