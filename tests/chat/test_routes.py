import os
os.environ.setdefault("LLM__OPENAI_API_KEY", "sk-test-fake")

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.chat.deps import get_chat_service
from app.chat.domain import Chat, ChatMessage
from app.chat.service import ChatService


def make_mock_service() -> ChatService:
    svc = MagicMock(spec=ChatService)
    svc.create_chat = AsyncMock()
    svc.get_chat = AsyncMock()
    svc.clear_history = AsyncMock()
    svc._repo = MagicMock()
    svc._repo.list_messages = AsyncMock()
    svc.send_message = MagicMock()
    return svc


@pytest.fixture
def client():
    svc = make_mock_service()
    app.dependency_overrides[get_chat_service] = lambda: svc
    yield TestClient(app), svc
    app.dependency_overrides.clear()


def test_create_chat(client):
    test_client, svc = client
    chat = Chat(owner_external_id="u1", interface="cli")
    svc.create_chat.return_value = chat

    resp = test_client.post("/chats", json={"owner_external_id": "u1", "interface": "cli"})
    assert resp.status_code == 200
    assert resp.json()["chat_id"] == str(chat.id)


def test_get_chat_found(client):
    test_client, svc = client
    chat = Chat(owner_external_id="u1", interface="cli")
    svc.get_chat.return_value = chat

    resp = test_client.get(f"/chats/{chat.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(chat.id)


def test_get_chat_not_found(client):
    test_client, svc = client
    svc.get_chat.return_value = None

    resp = test_client.get(f"/chats/{uuid4()}")
    assert resp.status_code == 404


def test_list_messages(client):
    test_client, svc = client
    chat_id = uuid4()
    msgs = [ChatMessage(chat_id=chat_id, role="user", content="hello")]
    svc._repo.list_messages.return_value = msgs

    resp = test_client.get(f"/chats/{chat_id}/messages")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["content"] == "hello"


def test_clear_messages(client):
    test_client, svc = client
    chat_id = uuid4()

    resp = test_client.delete(f"/chats/{chat_id}/messages")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    svc.clear_history.assert_called_once_with(chat_id)