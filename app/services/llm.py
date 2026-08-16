import hashlib
import json
import logging
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

from app.core.exceptions import LLMAuthError, LLMError, LLMRateLimitError, LLMTimeoutError
from app.schemas.chat import ChatDelta, ChatRequest, ChatResponse, Usage

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, client: AsyncOpenAI, cache, settings) -> None:
        self._client = client
        self._cache = cache
        self._settings = settings

    def _cache_key(self, req: ChatRequest) -> str:
        payload = req.model_dump(exclude={"user_id", "session_id"})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return f"chat:{digest}"

    async def complete(self, req: ChatRequest) -> ChatResponse:
        key = self._cache_key(req)

        cached = await self._cache.get(key)
        if cached:
            logger.info("cache hit key=%s", key[:16])
            response = ChatResponse.model_validate_json(cached)
            response.cached = True
            return response

        try:
            completion = await self._client.chat.completions.create(
                model=req.model,
                messages=[m.model_dump() for m in req.messages],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except openai.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except openai.OpenAIError as e:
            raise LLMError(str(e)) from e

        response = ChatResponse.from_openai(completion, cached=False)

        await self._cache.setex(key, self._settings.cache_ttl_seconds, response.model_dump_json())
        logger.info("cache set key=%s ttl=%d", key[:16], self._settings.cache_ttl_seconds)

        return response

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatDelta]:
        try:
            stream = await self._client.chat.completions.create(
                model=req.model,
                messages=[m.model_dump() for m in req.messages],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except openai.APITimeoutError as e:
            raise LLMTimeoutError(str(e)) from e
        except openai.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except openai.OpenAIError as e:
            raise LLMError(str(e)) from e

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield ChatDelta(content=chunk.choices[0].delta.content)
            if chunk.usage:
                yield ChatDelta(
                    usage=Usage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                    )
                )