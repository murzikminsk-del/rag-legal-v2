from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.services.llm_client import AsyncLLMClient

router = APIRouter()


class ChatRequest(BaseModel):
    prompt: str


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    client = AsyncLLMClient()

    async def generator():
        async for token in client.stream_chat(request.prompt):
            yield {"data": token}

    return EventSourceResponse(generator())