import asyncio
import logging
import time
import httpx

from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class AsyncLLMClient:
    def __init__(self, concurrency: int = 5) -> None:
        settings = get_settings()
        
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=30,
            max_retries=3,
            http_client=httpx.AsyncClient(trust_env=False),
        )
        self._model = settings.default_model
        self._sem = asyncio.Semaphore(concurrency)

    async def complete(self, prompt: str) -> str:
        start = time.perf_counter()
        status = "ok"
        try:
            async with self._sem:
                async with asyncio.timeout(15):
                    resp = await self._client.chat.completions.create(
                        model=self._model,
                        messages=[{"role": "user", "content": prompt}],
                    )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            status = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "llm.call duration_ms=%.1f model=%s prompt_chars=%d status=%s",
                duration_ms,
                self._model,
                len(prompt),
                status,
            )

    async def batch_chat(
        self, prompts: list[str], concurrency: int = 5
    ) -> list[str | Exception]:
        coros = [self.complete(p) for p in prompts]
        return list(await asyncio.gather(*coros, return_exceptions=True))

    async def stream_chat(self, prompt: str) -> AsyncIterator[str]:
        first_yield_at: float | None = None
        usage = None
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_yield_at is None:
                    first_yield_at = time.perf_counter()
                    logger.debug("stream_chat first token at %.3fs", first_yield_at)
                yield chunk.choices[0].delta.content
            if chunk.usage:
                usage = chunk.usage
        last_at = time.perf_counter()
        if usage:
            logger.info("stream_chat total_tokens=%d", usage.total_tokens)
        if first_yield_at:
            logger.info(
                "stream_chat TTFT=%.3fs total=%.3fs",
                first_yield_at,
                last_at,
            )