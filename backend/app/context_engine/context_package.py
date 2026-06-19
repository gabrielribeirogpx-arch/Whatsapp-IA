from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextPackage:
    tenant_id: Any = None
    conversation_id: Any = None
    session_id: Any = None
    flow_id: Any = None
    flow_version_id: Any = None
    node_id: Any = None
    provider_id: Any = None
    phone_number_id: Any = None
    external_user_id: Any = None
    trace_id: str = ""
    system_context: str = ""
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    session_variables: dict[str, Any] = field(default_factory=dict)
    memory_short: str = ""
    memory_long: list[dict[str, Any]] = field(default_factory=list)
    rag_chunks: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    contact_data: dict[str, Any] = field(default_factory=dict)
    tenant_metadata: dict[str, Any] = field(default_factory=dict)
    safe_metadata: dict[str, Any] = field(default_factory=dict)
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)

    def combined_prompt_section(self) -> str:
        sections: list[str] = []
        if self.memory_short:
            sections.append("=== HISTÓRICO RECENTE ===\n" + self.memory_short)
        if self.memory_long:
            sections.append("=== MEMÓRIA DO CONTATO ===\n" + "\n".join(f"- ({m.get('fact_type')}, score={float(m.get('score') or 0):.2f}) {m.get('fact_text')}" for m in self.memory_long))
        if self.rag_chunks:
            sections.append("=== BASE DE CONHECIMENTO ===\n" + "\n".join(str(c.get('content') if isinstance(c, dict) else c)[:1000] for c in self.rag_chunks))
        return "\n\n".join(sections)
