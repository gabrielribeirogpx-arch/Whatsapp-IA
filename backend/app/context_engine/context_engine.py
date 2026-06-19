from __future__ import annotations

import logging
import time
from typing import Any

from app.context_engine.context_package import ContextPackage
from app.context_engine.context_sources import ConversationSource, SessionVariableSource, LongMemorySource, RagSource, ToolOutputSource, TenantSource, ContactSource
from app.context_engine.limits import ContextLimits, estimate_tokens
from app.context_engine.sanitizer import sanitize_metadata

logger = logging.getLogger(__name__)


class UnifiedContextEngine:
    def __init__(self, db=None, limits: ContextLimits | None = None):
        self.db = db
        self.limits = limits or ContextLimits.defaults()
        self.sources = [TenantSource(), ContactSource(), ConversationSource(), SessionVariableSource(), LongMemorySource(), RagSource(), ToolOutputSource()]

    def build(self, *, tenant=None, conversation=None, session=None, flow=None, execution_context: dict[str, Any] | None = None, budget=None, flags: dict[str, Any] | None = None, **kwargs: Any) -> ContextPackage:
        started = time.monotonic()
        flags = flags or {}
        ctx = execution_context if isinstance(execution_context, dict) else {}
        tenant_id = kwargs.get("tenant_id") or getattr(tenant, "id", None) or getattr(session, "tenant_id", None) or ctx.get("tenant_id")
        trace_id = str(ctx.get("trace_id") or ctx.get("correlation_id") or flags.get("trace_id") or "")
        package = ContextPackage(
            tenant_id=tenant_id,
            conversation_id=kwargs.get("conversation_id") or getattr(conversation, "id", None) or ctx.get("conversation_id"),
            session_id=kwargs.get("session_id") or getattr(session, "id", None) or ctx.get("session_id"),
            flow_id=kwargs.get("flow_id") or getattr(flow, "id", None) or ctx.get("flow_id"),
            flow_version_id=kwargs.get("flow_version_id") or getattr(session, "flow_version_id", None) or ctx.get("flow_version_id"),
            node_id=kwargs.get("node_id") or ctx.get("node_id"),
            provider_id=kwargs.get("provider_id") or ctx.get("provider_id"),
            phone_number_id=kwargs.get("phone_number_id") or ctx.get("phone_number_id"),
            external_user_id=kwargs.get("external_user_id") or ctx.get("external_user_id"),
            trace_id=trace_id,
            system_context=str(flags.get("system_context") or ctx.get("system_context") or ""),
            safe_metadata=sanitize_metadata({**ctx, **flags}),
            budget_snapshot=budget.safe_metadata() if budget is not None and hasattr(budget, "safe_metadata") else {},
        )
        logger.info("event=context_build_started tenant_id=%s trace_id=%s", tenant_id, trace_id)
        source_kwargs = {**kwargs, "tenant": tenant, "tenant_id": tenant_id, "conversation": conversation, "session": session, "flow": flow, "execution_context": ctx, "limits": self.limits, "current_query": flags.get("current_query") or ctx.get("current_query") or kwargs.get("current_query", ""), "contact_id": kwargs.get("contact_id") or ctx.get("contact_id"), "contact": kwargs.get("contact"), "options": {}}
        options_by_source = flags.get("source_options") if isinstance(flags.get("source_options"), dict) else {}
        for source in self.sources:
            if source.name == "long_memory" and flags.get("include_long_memory", True) is False:
                continue
            if source.name == "rag" and flags.get("include_rag_context", False) is False:
                continue
            if source.name in {"conversation", "short_memory"} and flags.get("include_short_memory", True) is False:
                continue
            s_started = time.monotonic()
            try:
                data = source.load(self.db, **{**source_kwargs, "options": options_by_source.get(source.name, {})})
                for key, value in (data or {}).items():
                    if hasattr(package, key):
                        setattr(package, key, value)
                chars = len(str(data or ""))
                tokens = estimate_tokens(data)
                package.sources[source.name] = {"ok": True, "chars": chars, "estimated_tokens": tokens}
                logger.info("event=context_source_loaded tenant_id=%s trace_id=%s source=%s duration_ms=%s chars=%s estimated_tokens=%s", tenant_id, trace_id, source.name, int((time.monotonic()-s_started)*1000), chars, tokens)
            except Exception as exc:
                package.stats["fallback_used"] = True
                package.sources[source.name] = {"ok": False, "error": type(exc).__name__}
                logger.warning("event=context_source_failed tenant_id=%s trace_id=%s source=%s duration_ms=%s error=%s", tenant_id, trace_id, source.name, int((time.monotonic()-s_started)*1000), type(exc).__name__)
        self._fit_limits(package, budget)
        package.stats.update({"duration_ms": int((time.monotonic()-started)*1000), "chars": len(package.combined_prompt_section()), "estimated_tokens": estimate_tokens(package.combined_prompt_section())})
        logger.info("event=context_build_completed tenant_id=%s trace_id=%s duration_ms=%s chars=%s estimated_tokens=%s", tenant_id, trace_id, package.stats["duration_ms"], package.stats["chars"], package.stats["estimated_tokens"])
        return package

    def _fit_limits(self, package: ContextPackage, budget=None) -> None:
        max_chars = self.limits.max_context_chars
        max_tokens = self.limits.max_context_tokens
        if budget is not None:
            remaining = max(0, int(getattr(budget, "max_tokens_prompt", max_tokens)) - int(getattr(budget, "prompt_tokens_used", 0)))
            if remaining:
                max_tokens = min(max_tokens, remaining)
                max_chars = min(max_chars, remaining * 4)
        reduced: list[str] = []
        while len(package.combined_prompt_section()) > max_chars or estimate_tokens(package.combined_prompt_section()) > max_tokens:
            if package.conversation_history:
                package.conversation_history = package.conversation_history[1:]; reduced.append("history")
                package.memory_short = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in package.conversation_history)
            elif package.rag_chunks:
                package.rag_chunks = package.rag_chunks[:-1]; reduced.append("rag")
            elif package.memory_long:
                package.memory_long = package.memory_long[:-1]; reduced.append("memory")
            elif package.tool_outputs:
                package.tool_outputs = package.tool_outputs[:-1]; reduced.append("tool_outputs")
            else:
                break
        if reduced:
            package.safe_metadata["context_reduced"] = sorted(set(reduced))
