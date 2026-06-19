from __future__ import annotations

from typing import Any

from app.context_engine.sanitizer import sanitize_metadata, sanitize_value
class ConversationSource:
    name = "conversation"
    def load(self, db, *, tenant_id, session_id=None, limits=None, options=None, **_: Any) -> dict[str, Any]:
        opts = options or {}
        history = []
        history_text = ""
        if session_id:
            from app.services.flow_ai_memory_service import flow_ai_memory_service
            history = flow_ai_memory_service.get_recent_history(db, tenant_id=tenant_id, session_id=session_id, max_messages=opts.get("max_messages") or getattr(limits, "max_history_messages", 10), max_chars=opts.get("max_chars") or 4000)
            history_text = flow_ai_memory_service.build_history_for_prompt(history)
        return {"conversation_history": [{"role": getattr(h, "role", None), "content": getattr(h, "content", "")} for h in history], "memory_short": history_text}


class SessionVariableSource:
    name = "session_variables"
    def load(self, db, *, session=None, **_: Any) -> dict[str, Any]:
        variables = getattr(session, "variables", None) or getattr(session, "context", None) or {}
        return {"session_variables": sanitize_metadata(variables if isinstance(variables, dict) else {})}


class MemorySource(ConversationSource):
    name = "short_memory"


class LongMemorySource:
    name = "long_memory"
    def load(self, db, *, tenant_id, contact_id=None, current_query="", limits=None, options=None, **_: Any) -> dict[str, Any]:
        if not contact_id:
            return {"memory_long": []}
        opts = options or {}
        from app.services.long_term_memory_service import search_memory
        memories = search_memory(db, tenant_id, contact_id, current_query or "", top_k=opts.get("top_k") or getattr(limits, "max_long_memory_items", 5), min_similarity=opts.get("min_similarity", 0.25), fact_types=opts.get("fact_types"))
        return {"memory_long": sanitize_value(list(memories)[:getattr(limits, "max_long_memory_items", 5)])}


class RagSource:
    name = "rag"
    def load(self, db, *, limits=None, options=None, **_: Any) -> dict[str, Any]:
        opts = options or {}
        chunks = list(opts.get("chunks") or opts.get("rag_context") or [])[:getattr(limits, "max_rag_chunks", 10)]
        return {"rag_chunks": sanitize_value(chunks)}


class ToolOutputSource:
    name = "tool_outputs"
    def load(self, db, *, execution_context=None, limits=None, **_: Any) -> dict[str, Any]:
        ctx = execution_context if isinstance(execution_context, dict) else {}
        outputs = ctx.get("tool_outputs") or ctx.get("recent_tool_outputs") or []
        return {"tool_outputs": sanitize_value(list(outputs)[:getattr(limits, "max_tool_outputs", 5)] if isinstance(outputs, list) else [])}


class TenantSource:
    name = "tenant"
    def load(self, db, *, tenant=None, tenant_id=None, **_: Any) -> dict[str, Any]:
        raw = {"id": str(getattr(tenant, "id", tenant_id) or tenant_id or ""), "name": getattr(tenant, "name", None), "plan": getattr(tenant, "plan", None)}
        return {"tenant_metadata": sanitize_metadata(raw)}


class ContactSource:
    name = "contact"
    def load(self, db, *, contact=None, contact_id=None, **_: Any) -> dict[str, Any]:
        raw = {"id": str(getattr(contact, "id", contact_id) or contact_id or ""), "name": getattr(contact, "name", None), "phone": getattr(contact, "phone", None)}
        return {"contact_data": sanitize_metadata(raw)}
