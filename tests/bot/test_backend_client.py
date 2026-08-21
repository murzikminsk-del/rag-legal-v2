from uuid import UUID

import httpx
import pytest

from bot.services.backend_client import BackendClient


def make_client(transport: httpx.MockTransport) -> BackendClient:
    http = httpx.AsyncClient(transport=transport, base_url="http://test")
    return BackendClient(http)


@pytest.mark.asyncio
async def test_get_or_create_chat_returns_uuid():
    chat_id = "550e8400-e29b-41d4-a716-446655440000"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"chat_id": chat_id})

    client = make_client(httpx.MockTransport(handler))
    result = await client.get_or_create_chat("user-1", "telegram")
    assert result == UUID(chat_id)


@pytest.mark.asyncio
async def test_clear_messages_sends_delete():
    chat_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.method)
        return httpx.Response(200, json={"status": "ok"})

    client = make_client(httpx.MockTransport(handler))
    await client.clear_messages(chat_id)
    assert received == ["DELETE"]


@pytest.mark.asyncio
async def test_send_message_parses_sse():
    chat_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    tokens = ["Добрый", " день", "!", " Чем", " помочь?"]
    body = "".join(f"data: {t}\n\n" for t in tokens) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = make_client(httpx.MockTransport(handler))
    result = []
    async for token in await client.send_message(chat_id, "привет"):
        result.append(token)
    assert result == tokens