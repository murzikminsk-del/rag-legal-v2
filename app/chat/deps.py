from functools import lru_cache
from pathlib import Path

from fastapi import Depends, Request
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.chat.repositories.json_repo import JsonChatRepository
from app.chat.repositories.pg_repo import PostgresChatRepository
from app.chat.service import ChatService
from app.core.config import get_settings
from app.moderation.service import ModerationService

settings = get_settings()


@lru_cache
def _pg_sessionmaker():
    engine = create_async_engine(str(settings.database_url), echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_repository():
    repo_type = settings.chat_repository
    if repo_type == "json":
        yield JsonChatRepository(base_dir=settings.chat_storage_dir)
    elif repo_type == "postgres":
        session: AsyncSession = _pg_sessionmaker()()
        try:
            yield PostgresChatRepository(session=session)
        finally:
            await session.close()
    else:
        raise ValueError(
            f"Unknown CHAT_REPOSITORY value: {repo_type!r}. Use 'json' or 'postgres'."
        )


def get_llm_client() -> AsyncOpenAI:
    import httpx
    return AsyncOpenAI(
        api_key=settings.llm.openai_api_key.get_secret_value(),
        http_client=httpx.AsyncClient(trust_env=False),
    )


def get_moderation(request: Request) -> ModerationService:
    return request.app.state.moderation


async def get_chat_service(
    repo=Depends(get_repository),
    llm: AsyncOpenAI = Depends(get_llm_client),
    moderation: ModerationService = Depends(get_moderation),
) -> ChatService:
    return ChatService(repository=repo, llm=llm, moderation=moderation)