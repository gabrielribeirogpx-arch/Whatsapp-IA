from __future__ import annotations

from app.context_engine.context_package import ContextPackage


def legacy_context_dict(package: ContextPackage) -> dict:
    return {
        "conversation_history": package.conversation_history,
        "long_term_memory": package.memory_long,
        "rag_context": package.rag_chunks,
        "combined_prompt_section": package.combined_prompt_section(),
        "metadata": {
            "short_memory_count": len(package.conversation_history),
            "long_memory_count": len(package.memory_long),
            "rag_context_count": len(package.rag_chunks),
            "memory_latency_ms": package.stats.get("duration_ms", 0),
            "fallback_used": bool(package.stats.get("fallback_used")),
            "unified_context_engine": True,
            **package.safe_metadata,
        },
        "context_package": package,
    }
