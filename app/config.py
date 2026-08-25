from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # SettingsConfigDict говорит: читай переменные из файла .env
    # env_file_encoding — кодировка файла (важно для Windows)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # лишние переменные в .env не вызывают ошибку
    )

    # SecretStr — специальный тип: значение не печатается в логах случайно
    openai_api_key: SecretStr

    # Модель GPT, которую будем использовать
    default_model: str = "gpt-4.1-mini"

    # Таймаут запроса в секундах
    request_timeout: float = 30.0
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Postgres
    database_url: str = "postgresql+asyncpg://app:secret@localhost:5432/rag_legal"

    # Observability
    log_level: str = "INFO"
    phoenix_collector_endpoint: str = "http://localhost:6006"

    # Хранилище чатов: "json" или "postgres"
    chat_repository: str = "json"
    chat_storage_dir: str = "./var/chats"

    # Стратегия контекста: "sliding" или "hybrid"
    chat_context_strategy: str = "hybrid"

    # Sliding window: сколько последних сообщений брать
    chat_context_window: int = 10

    # Лимит запросов в минуту (rate limiting)
    rate_limit_per_minute: int = 30


# lru_cache — кешируем: Settings() создаётся один раз, не при каждом вызове
@lru_cache
def get_settings() -> Settings:
    return Settings()