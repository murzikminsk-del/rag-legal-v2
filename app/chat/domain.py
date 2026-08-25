from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    chat_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    tokens: int | None = None
    created_at: datetime = Field(default_factory=_now)
    media_refs: dict | None = None


class Chat(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_external_id: str
    interface: str
    system_prompt: str | None = None
    created_at: datetime = Field(default_factory=_now)