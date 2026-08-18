import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps.providers import LLMServiceDep
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.security.input_validator import validate_input
from app.services.security.output_filter import filter_output

router = APIRouter(tags=["chat"])


def _extract_system_prompt(req: ChatRequest) -> str:
    for msg in req.messages:
        if msg.role == "system":
            return msg.content
    return ""


@router.post(
    "/chat",
    summary="Synchronous chat completion",
    response_model=ChatResponse,
    responses={400: {}, 429: {}, 502: {}, 504: {}},
)
async def chat(req: ChatRequest, request: Request, service: LLMServiceDep) -> ChatResponse:
    for msg in req.messages:
        if msg.role == "user":
            result = validate_input(msg.content)
            if not result.ok:
                raise HTTPException(status_code=400, detail={"rule": result.rule, "reason": result.reason})

    response = await service.complete(req)

    system_prompt = _extract_system_prompt(req)
    canary = getattr(request.app.state, "canary", "")
    try:
        response.content = filter_output(response.content, system_prompt, canary)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return response


@router.post(
    "/chat/stream",
    summary="Streaming chat completion (SSE)",
    responses={400: {}, 429: {}, 502: {}, 504: {}},
)
async def chat_stream(req: ChatRequest, request: Request, service: LLMServiceDep):
    for msg in req.messages:
        if msg.role == "user":
            result = validate_input(msg.content)
            if not result.ok:
                raise HTTPException(status_code=400, detail={"rule": result.rule, "reason": result.reason})

    async def generator():
        async for delta in service.stream(req):
            if delta.content is not None:
                yield f"data: {delta.content}\n\n"
            elif delta.usage is not None:
                yield f"data: {json.dumps({'usage': delta.usage.model_dump()})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")