"""Central usage vocabulary; do not use untyped metric strings in callers."""
from enum import Enum


class UsageMetric(str, Enum):
    ACTIVE_USERS = "active_users"
    WHATSAPP_NUMBERS = "whatsapp_numbers"
    PUBLISHED_FLOWS = "published_flows"
    ACTIVE_INTEGRATIONS = "active_integrations"
    KNOWLEDGE_DOCUMENTS = "knowledge_documents"
    CONVERSATIONS_CREATED = "conversations_created"
    MESSAGES_INBOUND = "messages_inbound"
    MESSAGES_OUTBOUND = "messages_outbound"
    FLOW_EXECUTIONS = "flow_executions"
    AI_EXECUTIONS = "ai_executions"
    AI_INPUT_TOKENS = "ai_input_tokens"
    AI_OUTPUT_TOKENS = "ai_output_tokens"
    AI_TOTAL_TOKENS = "ai_total_tokens"
    AI_COST_CENTS = "ai_cost_cents"
    OBSERVABILITY_EVENTS = "observability_events"
    EXPORT_JOBS = "export_jobs"
    STORAGE_BYTES = "storage_bytes"
    VECTOR_STORAGE_BYTES = "vector_storage_bytes"


STOCK_METRICS = {UsageMetric.ACTIVE_USERS, UsageMetric.WHATSAPP_NUMBERS, UsageMetric.PUBLISHED_FLOWS, UsageMetric.ACTIVE_INTEGRATIONS, UsageMetric.KNOWLEDGE_DOCUMENTS, UsageMetric.STORAGE_BYTES, UsageMetric.VECTOR_STORAGE_BYTES}
