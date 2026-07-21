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
    billing_ui_enabled: bool = os.getenv("BILLING_UI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


settings = Settings()
