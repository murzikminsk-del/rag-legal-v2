import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.chat.repositories.pg_models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if db_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata

# LangGraph-чекпоинтер ведёт свои таблицы через setup() — без SQLAlchemy-моделей.
# Исключаем из autogenerate, иначе Alembic предложит их DROP.
_CHECKPOINT_TABLES = {
    "checkpoints",
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoint_migrations",
}


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    if type_ == "table" and name in _CHECKPOINT_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())