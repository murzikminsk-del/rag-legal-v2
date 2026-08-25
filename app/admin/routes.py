import json
from datetime import datetime, timezone, timedelta

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from functools import lru_cache

from app.core.config import get_settings

log = structlog.get_logger()
settings = get_settings()

router = APIRouter(prefix="/chats/admin", tags=["admin"])


# --- Auth ---

async def require_admin(x_admin_token: str = Header(...)):
    if x_admin_token != settings.admin_token.get_secret_value():
        raise HTTPException(status_code=401, detail="Invalid admin token")


# --- DB session (только для postgres-режима) ---

@lru_cache
def _engine():
    return create_async_engine(str(settings.database_url), echo=False)


async def _get_session():
    session = AsyncSession(_engine(), expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()


# --- Schemas ---

class StatsOut(BaseModel):
    total_messages: int
    active_users: int
    avg_latency_ms: float | None
    moderation_block_rate: float | None
    feedback_up_ratio: float | None


class UserOut(BaseModel):
    owner_external_id: str
    chat_count: int
    last_seen_at: datetime | None


class BroadcastIn(BaseModel):
    message: str
    interface_filter: str = "telegram"


# --- Endpoints ---

@router.get("/stats", response_model=StatsOut)
async def get_stats(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(_get_session),
) -> StatsOut:
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    row = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE role = 'user') AS total_messages,
                COUNT(DISTINCT c.owner_external_id)   AS active_users
            FROM chat_messages m
            JOIN chats c ON c.id = m.chat_id
            WHERE m.created_at >= :since AND m.deleted_at IS NULL
        """),
        {"since": since},
    )
    stats = row.mappings().one()

    feedback_row = await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE value = 'up')::float /
                NULLIF(COUNT(*), 0) AS up_ratio
            FROM message_feedback
            WHERE created_at >= :since
        """),
        {"since": since},
    )
    feedback = feedback_row.mappings().one()

    return StatsOut(
        total_messages=stats["total_messages"],
        active_users=stats["active_users"],
        avg_latency_ms=None,
        moderation_block_rate=None,
        feedback_up_ratio=feedback["up_ratio"],
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    limit: int = 50,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(_get_session),
) -> list[UserOut]:
    rows = await session.execute(
        text("""
            SELECT
                c.owner_external_id,
                COUNT(c.id) AS chat_count,
                MAX(m.created_at) AS last_seen_at
            FROM chats c
            LEFT JOIN chat_messages m ON m.chat_id = c.id AND m.deleted_at IS NULL
            GROUP BY c.owner_external_id
            ORDER BY last_seen_at DESC NULLS LAST
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return [
        UserOut(
            owner_external_id=r["owner_external_id"],
            chat_count=r["chat_count"],
            last_seen_at=r["last_seen_at"],
        )
        for r in rows.mappings()
    ]


@router.post("/broadcast", status_code=202)
async def broadcast(
    body: BroadcastIn,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(_get_session),
) -> dict:
    from app.services.broadcaster import broadcast as do_broadcast

    # Получаем всех пользователей нужного интерфейса
    rows = await session.execute(
        text("SELECT DISTINCT owner_external_id FROM chats WHERE interface = :iface"),
        {"iface": body.interface_filter},
    )
    owner_ids = []
    for r in rows.mappings():
        try:
            owner_ids.append(int(r["owner_external_id"]))
        except (ValueError, TypeError):
            pass

    # Записываем в очередь как аудит-лог
    await session.execute(
        text("""
            INSERT INTO broadcast_queue (message, interface, status, created_at)
            VALUES (:message, :interface, 'pending', NOW())
        """),
        {"message": body.message, "interface": body.interface_filter},
    )
    await session.commit()

    if not owner_ids:
        return {"status": "queued", "sent": 0, "failed": 0}

    result = await do_broadcast(
        text=body.message,
        owner_ids=owner_ids,
        bot_url=settings.bot_url,
        internal_token=settings.internal_token.get_secret_value(),
    )
    log.info("broadcast_done", **result)
    return {"status": "sent", **result}