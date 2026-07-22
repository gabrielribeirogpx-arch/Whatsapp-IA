import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    verify_token: str = os.getenv("VERIFY_TOKEN", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    whatsapp_token: str = os.getenv("WHATSAPP_TOKEN", "")
    phone_number_id: str = os.getenv("PHONE_NUMBER_ID", "")
    whatsapp_phone_id: str = os.getenv("WHATSAPP_PHONE_ID", "")
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    oauth_token_encryption_key: str = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "")
    billing_enforcement_enabled: bool = os.getenv("BILLING_ENFORCEMENT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    # The boolean remains the emergency/master switch.  A mode is deliberately
    # required as the second switch so production can observe decisions before
    # it starts refusing writes.
    billing_enforcement_mode: str = os.getenv("BILLING_ENFORCEMENT_MODE", "observe").lower()
    billing_enforce_users: bool = os.getenv("BILLING_ENFORCE_USERS", "false").lower() in {"1", "true", "yes", "on"}
    billing_enforce_whatsapp: bool = os.getenv("BILLING_ENFORCE_WHATSAPP", "false").lower() in {"1", "true", "yes", "on"}
    billing_enforce_flows: bool = os.getenv("BILLING_ENFORCE_FLOWS", "false").lower() in {"1", "true", "yes", "on"}
    billing_enforce_ai: bool = os.getenv("BILLING_ENFORCE_AI", "false").lower() in {"1", "true", "yes", "on"}
    billing_enforce_mcp: bool = os.getenv("BILLING_ENFORCE_MCP", "false").lower() in {"1", "true", "yes", "on"}
    billing_enforce_observability: bool = os.getenv("BILLING_ENFORCE_OBSERVABILITY", "false").lower() in {"1", "true", "yes", "on"}
    billing_ui_enabled: bool = os.getenv("BILLING_UI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    stripe_enabled: bool = os.getenv("STRIPE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe_publishable_key: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    stripe_success_url: str = os.getenv("STRIPE_SUCCESS_URL", "")
    stripe_cancel_url: str = os.getenv("STRIPE_CANCEL_URL", "")
    stripe_portal_return_url: str = os.getenv("STRIPE_PORTAL_RETURN_URL", "")


settings = Settings()
