import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.chat.repositories.json_repo import JsonChatRepository
from app.chat.repositories.pg_models import Base
from app.chat.repositories.pg_repo import PostgresChatRepository

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PG_URL = "postgresql+asyncpg://app:secret@localhost:5433/rag_legal?ssl=disable"


@pytest_asyncio.fixture(params=["json", "postgres"])
async def repo(request, tmp_path: Path):
    if request.param == "json":
        yield JsonChatRepository(base_dir=tmp_path)
        return

    pytest.skip("asyncpg + Windows ProactorEventLoop несовместимы с localhost Docker — запускать внутри контейнера")
    engine = create_async_engine(PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    session = Session()
    try:
        yield PostgresChatRepository(session=session)
    finally:
        await session.rollback()
        await session.close()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()