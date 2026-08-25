import hashlib
import os

import diskcache
import httpx
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

_cache: diskcache.Cache | None = None


def _get_cache() -> diskcache.Cache:
    global _cache
    if _cache is None:
        settings = get_settings()
        path = settings.embedding_cache_dir
        path.mkdir(parents=True, exist_ok=True)
        _cache = diskcache.Cache(str(path))
    return _cache


def _cache_key(model: str, text: str) -> str:
    return "emb:" + hashlib.sha256(f"{model}\x00{text}".encode()).hexdigest()


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    reraise=True,
)
async def _api_batch(
    client: AsyncOpenAI, model: str, texts: list[str]
) -> list[list[float]]:
    resp = await client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]


async def embed_texts(
    texts: list[str], model: str | None = None
) -> list[list[float]]:
    """
    Возвращает L2-нормализованные эмбеддинги для списка текстов.
    Повторный вызов с теми же текстами читает из диска, API не вызывает.
    Ключ кеша включает имя модели — смена EMBEDDING_MODEL автоматически
    обходит старые записи.
    """
    if not texts:
        return []

    settings = get_settings()
    model = model or settings.embedding_model
    batch_size = settings.embedding_batch_size
    cache = _get_cache()

    result: list[list[float] | None] = [None] * len(texts)
    uncached: list[tuple[int, str]] = []

    for i, text in enumerate(texts):
        hit = cache.get(_cache_key(model, text))
        if hit is not None:
            result[i] = hit
        else:
            uncached.append((i, text))

    if uncached:
        client = AsyncOpenAI(
            api_key=settings.llm.openai_api_key.get_secret_value(),
            http_client=httpx.AsyncClient(
                proxy=os.environ.get("HTTPS_PROXY"),
                verify=False,
            ),
        )
        try:
            for start in range(0, len(uncached), batch_size):
                chunk = uncached[start : start + batch_size]
                embeddings = await _api_batch(
                    client, model, [t for _, t in chunk]
                )
                for (orig_i, text), emb in zip(chunk, embeddings):
                    cache.set(_cache_key(model, text), emb)
                    result[orig_i] = emb
        finally:
            await client.close()

    return result  # type: ignore[return-value]