import pytest
from unittest.mock import AsyncMock, MagicMock

import openai

from app.core.exceptions import LLMAuthError, LLMRateLimitError
from app.schemas.chat import ChatRequest, ChatResponse, Message, Usage, calculate_cost
from app.services.llm import LLMService


# ── вспомогательные фикстуры ─────────────────────────────────────────────

def make_completion(content="Ответ", model="gpt-4.1-mini",
                    prompt_tokens=10, completion_tokens=20):
    """Строим mock объекта ChatCompletion вручную."""
    c = MagicMock()
    c.model = model
    c.choices = [MagicMock()]
    c.choices[0].message.content = content
    c.choices[0].finish_reason = "stop"
    c.usage.prompt_tokens = prompt_tokens
    c.usage.completion_tokens = completion_tokens
    c.usage.total_tokens = prompt_tokens + completion_tokens
    return c


@pytest.fixture
def settings():
    s = MagicMock()
    s.cache_ttl_seconds = 3600
    return s


@pytest.fixture
def base_req():
    return ChatRequest(
        messages=[Message(role="user", content="Что такое исковая давность?")]
    )


# ── тест 1: cache hit — OpenAI API не вызывается ─────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_skips_api_call(settings, base_req):
    cached = ChatResponse(
        content="Из кеша",
        model="gpt-4.1-mini",
        usage=Usage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
        finish_reason="stop",
        cached=False,
    )
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=cached.model_dump_json())

    client = AsyncMock()
    service = LLMService(client=client, cache=cache, settings=settings)
    result = await service.complete(base_req)

    assert result.cached is True
    assert result.content == "Из кеша"
    client.chat.completions.create.assert_not_called()


# ── тест 2: cache miss — API вызван, результат сохранён в кеш ────────────

@pytest.mark.asyncio
async def test_cache_miss_calls_api_and_stores(settings, base_req):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.setex = AsyncMock()

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=make_completion(content="Ответ API")
    )

    service = LLMService(client=client, cache=cache, settings=settings)
    result = await service.complete(base_req)

    assert result.content == "Ответ API"
    assert result.cached is False
    cache.setex.assert_called_once()


# ── тест 3: RateLimitError → LLMRateLimitError ───────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_maps_to_llm_rate_limit_error(settings, base_req):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=openai.RateLimitError(
            "rate limit exceeded", response=MagicMock(), body={}
        )
    )

    service = LLMService(client=client, cache=cache, settings=settings)
    with pytest.raises(LLMRateLimitError):
        await service.complete(base_req)


# ── тест 4: AuthenticationError → LLMAuthError ───────────────────────────

@pytest.mark.asyncio
async def test_auth_error_maps_to_llm_auth_error(settings, base_req):
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=openai.AuthenticationError(
            "invalid api key", response=MagicMock(), body={}
        )
    )

    service = LLMService(client=client, cache=cache, settings=settings)
    with pytest.raises(LLMAuthError):
        await service.complete(base_req)


# ── тест 5: ключ кеша не зависит от user_id и session_id ─────────────────

def test_cache_key_excludes_user_id_and_session(settings):
    service = LLMService(client=MagicMock(), cache=MagicMock(), settings=settings)

    req1 = ChatRequest(
        messages=[Message(role="user", content="Вопрос")],
        user_id="alice", session_id="sess-1",
    )
    req2 = ChatRequest(
        messages=[Message(role="user", content="Вопрос")],
        user_id="bob", session_id="sess-99",
    )
    assert service._cache_key(req1) == service._cache_key(req2)


# ── тест 6: ключ кеша меняется при смене модели ───────────────────────────

def test_cache_key_differs_by_model(settings):
    service = LLMService(client=MagicMock(), cache=MagicMock(), settings=settings)

    req_mini = ChatRequest(
        messages=[Message(role="user", content="Вопрос")], model="gpt-4.1-mini"
    )
    req_full = ChatRequest(
        messages=[Message(role="user", content="Вопрос")], model="gpt-4.1"
    )
    assert service._cache_key(req_mini) != service._cache_key(req_full)


# ── тест 7: ChatResponse.from_openai корректно парсит все поля ────────────

def test_chat_response_from_openai_maps_all_fields():
    completion = make_completion(
        content="Три года", model="gpt-4.1-mini",
        prompt_tokens=15, completion_tokens=25,
    )
    resp = ChatResponse.from_openai(completion)

    assert resp.content == "Три года"
    assert resp.model == "gpt-4.1-mini"
    assert resp.usage.prompt_tokens == 15
    assert resp.usage.completion_tokens == 25
    assert resp.usage.total_tokens == 40
    assert resp.finish_reason == "stop"
    assert resp.cached is False


# ── тест 8: ChatRequest не принимает пустой список сообщений ──────────────

def test_chat_request_empty_messages_raises_validation_error():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(messages=[])


# ── тест 9: calculate_cost правильно считает стоимость ───────────────────

def test_calculate_cost_gpt4_mini():
    usage = Usage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
    cost = calculate_cost("gpt-4.1-mini", usage)
    # 1000 * 0.40/1M + 1000 * 1.60/1M = $0.002
    assert abs(cost - 0.002) < 1e-9


# ── тест 10: Message.__repr__ маскирует PII ───────────────────────────────

def test_message_repr_masks_pii():
    msg = Message(role="user", content="Мой email test@example.com")
    assert "test@example.com" not in repr(msg)
    assert "[EMAIL]" in repr(msg)
    