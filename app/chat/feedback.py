from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.routes import _get_session

router = APIRouter(prefix="/chats", tags=["feedback"])


class FeedbackIn(BaseModel):
    value: str  # "up" | "down"


@router.post("/{chat_id}/messages/{message_id}/feedback", status_code=204)
async def save_feedback(
    chat_id: UUID,
    message_id: UUID,
    body: FeedbackIn,
    session: AsyncSession = Depends(_get_session),
) -> None:
    if body.value not in ("up", "down"):
        raise HTTPException(status_code=422, detail="value must be 'up' or 'down'")

    # owner_external_id берём из чата по chat_id
    row = await session.execute(
        text("SELECT owner_external_id FROM chats WHERE id = :chat_id"),
        {"chat_id": chat_id},
    )
    chat = row.mappings().one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    await session.execute(
        text("""
            INSERT INTO message_feedback (message_id, owner_external_id, value)
            VALUES (:message_id, :owner, :value)
            ON CONFLICT (owner_external_id, message_id) DO UPDATE SET value = :value
        """),
        {
            "message_id": message_id,
            "owner": chat["owner_external_id"],
            "value": body.value,
        },
    )
    await session.commit()