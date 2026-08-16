import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.deps.providers import LLMServiceDep
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    summary="Synchronous chat completion",
    response_model=ChatResponse,
    responses={429: {}, 502: {}, 504: {}},
)
async def chat(req: ChatRequest, service: LLMServiceDep) -> ChatResponse:
    return await service.complete(req)


@router.post(
    "/chat/stream",
    summary="Streaming chat completion (SSE)",
    responses={429: {}, 502: {}, 504: {}},
)
async def chat_stream(req: ChatRequest, service: LLMServiceDep):
    async def generator():
        async for delta in service.stream(req):
            if delta.content is not None:
                yield f"data: {delta.content}\n\n"
            elif delta.usage is not None:
                yield f"data: {json.dumps({'usage': delta.usage.model_dump()})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")