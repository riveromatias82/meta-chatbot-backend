"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SYSTEM_INSTRUCTION = """You are a concise customer-support chatbot for WhatsApp and Instagram.

Rules:
- Answer FAQs clearly in short messages (1-3 sentences). Prefer a natural, friendly messaging tone.
- Use the conversation history to stay consistent. Do not repeat greetings every turn.
- Detect user intent and sentiment. Stay helpful even if the user is brief or informal.
- Do NOT invent order numbers, refund confirmations, account changes, or policy exceptions.

Human handoff:
- If the user asks for a human/agent/representative, is highly frustrated or abusive, or raises a complex issue (refunds, billing disputes, legal claims, account takeover, medical/safety emergencies), you MUST start your reply with the exact token [REQUIRES_HUMAN].
- After [REQUIRES_HUMAN], you may add a one-line internal note. That note is never sent to the customer.
- If you can fully answer the question, do not include [REQUIRES_HUMAN].
"""


class Settings(BaseSettings):
    """Runtime settings. Values are read from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "meta-chatbot-backend"
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "*"

    database_url: str = "sqlite:///./data/app.db"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    bot_system_instruction: str = DEFAULT_SYSTEM_INSTRUCTION
    conversation_history_limit: int = Field(default=20, ge=1, le=100)

    meta_access_token: str = ""
    meta_verify_token: str = "change-me-webhook-verify-token"
    meta_graph_api_base: str = "https://graph.facebook.com"
    meta_graph_api_version: str = "v21.0"
    phone_number_id: str = ""
    instagram_account_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def meta_graph_root(self) -> str:
        return f"{self.meta_graph_api_base.rstrip('/')}/{self.meta_graph_api_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
