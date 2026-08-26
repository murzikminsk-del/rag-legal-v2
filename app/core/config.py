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
    
    admin_token: SecretStr = SecretStr("change-me-admin")
    use_openai_moderation: bool = True
    moderation_keywords_path: Path = Path("moderation_keywords.yaml")

    embedding_model: str = "text-embedding-3-small"
    embedding_cache_dir: Path = Path(".cache/embeddings")
    embedding_batch_size: int = 100
    
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "documents"
    embedding_dim: int = 1536
    
    rag_collection: str = "rag_block_03"
    rag_baremetal_collection: str = "rag_block_03_baremetal"
    rag_corpus_dir: Path = Path("data/rag-block-03")
    chunk_size: int = 512
    chunk_overlap: int = 64
    similarity_top_k: int = 10
    rag_score_threshold: float = 0.3
    cohere_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()