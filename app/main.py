import time
import uuid
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
import structlog.contextvars
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError
from app.observability.logging import setup_logging
from app.observability.tracing import setup_tracing
from app.routers import chat, health, models

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    setup_logging(settings.log_level)
    setup_tracing()

    app.state.openai = AsyncOpenAI(
        api_key=settings.llm.openai_api_key.get_secret_value(),
        timeout=settings.llm.request_timeout,
        http_client=httpx.AsyncClient(trust_env=False),
    )
    app.state.cache = aioredis.from_url(settings.redis_url, decode_responses=True, protocol=2)

    logger.info("startup", message="OpenAI and Redis clients initialized")
    yield

    await app.state.openai.close()
    await app.state.cache.aclose()
    logger.info("shutdown", message="clients closed")


settings = get_settings()

app = FastAPI(
    title="RAG Legal Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    structlog.contextvars.clear_contextvars()

    request_id = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "http_request",
        status=response.status_code,
        duration_ms=round(duration_ms, 1),
    )
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    if isinstance(exc, LLMRateLimitError):
        status = 429
    elif isinstance(exc, LLMTimeoutError):
        status = 504
    else:
        status = 502
    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": {"details": errors}})


app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat.router)