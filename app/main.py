import secrets
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

from app.chat.routes import router as chat_history_router
from app.admin.routes import router as admin_router
from app.chat.feedback import router as feedback_router
from app.moderation.service import ModerationService
from app.services.vector_store import get_vector_store

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    setup_tracing()
    app.state.openai = AsyncOpenAI(
        api_key=settings.llm.openai_api_key.get_secret_value(),
        timeout=settings.llm.request_timeout,
        http_client=httpx.AsyncClient(trust_env=False),
    )
    app.state.cache = aioredis.from_url(settings.redis_url, decode_responses=True, protocol=2)
    app.state.moderation = ModerationService(
        llm=app.state.openai,
        keywords_path=settings.moderation_keywords_path,
        use_openai=settings.use_openai_moderation,
    )    
    
    vector_store = get_vector_store()
    await vector_store.ensure_collection()
    app.state.vector_store = vector_store    
    
    app.state.canary = "CANARY_" + secrets.token_hex(4)
    logger.info("startup", message="OpenAI and Redis clients initialized")
    yield
    await app.state.openai.close()
    await app.state.cache.aclose()
    await app.state.vector_store.close()
    logger.info("shutdown", message="clients closed")


app = FastAPI(title="RAG Legal Assistant", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path not in ("/chat", "/chat/stream"):
        return await call_next(request)
    key = f"rl:{request.client.host}"
    cache = request.app.state.cache
    count = await cache.incr(key)
    if count == 1:
        await cache.expire(key, 60)
    if count > settings.rate_limit_per_min:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limit_exceeded", "message": f"Max {settings.rate_limit_per_min} requests per minute"}},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)


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
    logger.info("http_request", status=response.status_code, duration_ms=round(duration_ms, 1))
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
    return JSONResponse(status_code=status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"details": errors}})


app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(chat_history_router)
app.include_router(admin_router)
app.include_router(feedback_router)
