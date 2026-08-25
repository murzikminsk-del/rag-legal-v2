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
async def test_send_message_parses_json_sse():
    chat_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    body = (
        'data: {"type":"token","delta":"Добрый"}\n\n'
        'data: {"type":"token","delta":" день"}\n\n'
        'data: {"type":"done"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = make_client(httpx.MockTransport(handler))
    result = []
    async for token in client.send_message(chat_id, "привет"):
        result.append(token)
    assert result == ["Добрый", " день"]


@pytest.mark.asyncio
async def test_send_message_with_media_sends_multipart():
    chat_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    body = 'data: {"type":"token","delta":"ок"}\n\ndata: {"type":"done"}\n\n'
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["content_type"] = request.headers.get("content-type", "")
        received["has_body"] = len(request.content) > 0
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = make_client(httpx.MockTransport(handler))
    result = []
    async for token in client.send_message(chat_id, "опиши", media=b"fake", mime="image/jpeg"):
        result.append(token)

    assert result == ["ок"]
    assert "multipart" in received["content_type"]