from enum import StrEnum


class FeatureKey(StrEnum):
    DASHBOARD="dashboard"; INBOX="inbox"; CRM="crm"; PIPELINE="pipeline"; FLOWS="flows"; INTEGRATIONS="integrations"; ACADEMY="academy"
    USERS="users"; WHATSAPP_NUMBERS="whatsapp_numbers"; PUBLISHED_FLOWS="published_flows"; MONTHLY_CONVERSATIONS="monthly_conversations"; MONTHLY_MESSAGES="monthly_messages"; MONTHLY_FLOW_EXECUTIONS="monthly_flow_executions"; STORAGE_BYTES="storage_bytes"
    AI_ENABLED="ai_enabled"; AI_AGENT="ai_agent"; AI_SYSTEM="ai_system"; AI_MEMORY="ai_memory"; AI_PLAYGROUND="ai_playground"; AI_RAG="ai_rag"; AI_MONTHLY_CREDIT_CENTS="ai_monthly_credit_cents"
    MCP="mcp"; API_ACCESS="api_access"; WEBHOOKS="webhooks"; GOOGLE_CALENDAR="google_calendar"
    OBSERVABILITY="observability"; OBSERVABILITY_RETENTION_DAYS="observability_retention_days"; OBSERVABILITY_EXPORTS="observability_exports"; OBSERVABILITY_REPLAY="observability_replay"; OBSERVABILITY_INFRASTRUCTURE="observability_infrastructure"
    ADVANCED_ROLES="advanced_roles"; AUDIT="audit"; SSO="sso"; PRIORITY_SUPPORT="priority_support"


ALL_FEATURE_KEYS = tuple(feature.value for feature in FeatureKey)
