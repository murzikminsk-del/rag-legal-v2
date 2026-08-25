import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.deps import get_chat_service
from app.chat.domain import Chat, ChatMessage
from app.chat.media import media_to_part
from app.chat.service import ChatService
from app.deps.providers import get_openai

router = APIRouter(prefix="/chats", tags=["chat"])


class CreateChatIn(BaseModel):
    owner_external_id: str
    interface: str
    system_prompt: str | None = None


class CreateChatOut(BaseModel):
    chat_id: UUID


class SystemMessageIn(BaseModel):
    text: str
    notify: bool = False


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
    content: str = Form(...),
    media: UploadFile | None = File(None),
    service: ChatService = Depends(get_chat_service),
    llm=Depends(get_openai),
) -> StreamingResponse:
    # check_input здесь — до StreamingResponse, HTTPException обработается нормально
    await service.check_input(content)

    media_part: dict | None = None
    media_meta: dict | None = None

    if media is not None:
        media_part = await media_to_part(media, llm)
        media_meta = {
            "mime": media.content_type,
            "size": media.size,
            "filename": media.filename,
            "part": media_part,
        }

    async def generator():
        async for event in service.send_message(
            chat_id, content, media_part=media_part, media_meta=media_meta
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

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


@router.post("/{chat_id}/system-message")
async def system_message(
    chat_id: UUID,
    body: SystemMessageIn,
    service: ChatService = Depends(get_chat_service),
) -> dict:
    chat = await service.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    msg = ChatMessage(chat_id=chat_id, role="assistant", content=body.text)
    await service._repo.append_message(chat_id, msg)

    if body.notify and chat.owner_external_id:
        from app.services.notifier import notify_user
        try:
            await notify_user(int(chat.owner_external_id), body.text)
        except Exception:
            pass

    return {"status": "ok"}
