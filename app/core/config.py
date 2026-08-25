from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM__", extra="ignore")
    openai_api_key: SecretStr
    request_timeout: float = 30.0
    default_model: str = "gpt-4.1-mini"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMSettings = LLMSettings()

    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"
    rate_limit_per_min: int = 30

    database_url: str = "postgresql+asyncpg://app:secret@localhost:5433/rag_legal"

    chat_repository: Literal["json", "postgres"] = "json"
    chat_storage_dir: Path = Path("./var/chats")
    chat_context_strategy: Literal["sliding", "hybrid"] = "sliding"
    chat_context_window: int = 10
    bot_url: str = "http://bot:9000"
    internal_token: SecretStr = SecretStr("change-me")
    bot_api_port: int = 9000


@lru_cache
def get_settings() -> Settings:
    return Settings()