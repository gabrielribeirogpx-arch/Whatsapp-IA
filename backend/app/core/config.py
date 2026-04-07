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


settings = Settings()
