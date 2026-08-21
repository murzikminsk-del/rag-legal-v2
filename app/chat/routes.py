from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.deps import get_chat_service
from app.chat.domain import Chat, ChatMessage
from app.chat.service import ChatService

router = APIRouter(prefix="/chats", tags=["chat"])


class CreateChatIn(BaseModel):
    owner_external_id: str
    interface: str
    system_prompt: str | None = None


class CreateChatOut(BaseModel):
    chat_id: UUID


class MessageIn(BaseModel):
    content: str


@router.post("", response_model=CreateChatOut)
async def create_chat(
    body: CreateChatIn,
    service: ChatService = Depends(get_chat_service),
) -> CreateChatOut:
    chat = await service.create_chat(
        owner_external_id=body.owner_external_id,
        interface=body.interface,
        system_prompt=body.system_prompt,
    )
    return CreateChatOut(chat_id=chat.id)


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: UUID,
    body: MessageIn,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    async def generator():
        async for chunk in service.send_message(chat_id, body.content):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/{chat_id}/messages", response_model=list[ChatMessage])
async def list_messages(
    chat_id: UUID,
    limit: int = 50,
    service: ChatService = Depends(get_chat_service),
) -> list[ChatMessage]:
    return await service._repo.list_messages(chat_id, limit=limit)


@router.delete("/{chat_id}/messages")
async def clear_messages(
    chat_id: UUID,
    service: ChatService = Depends(get_chat_service),
) -> dict:
    await service.clear_history(chat_id)
    return {"status": "ok"}


@router.get("/{chat_id}", response_model=Chat)
async def get_chat(
    chat_id: UUID,
    service: ChatService = Depends(get_chat_service),
) -> Chat:
    chat = await service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat