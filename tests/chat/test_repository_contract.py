import pytest
from uuid import uuid4

from app.chat.domain import ChatMessage


@pytest.mark.asyncio
async def test_create_and_get_chat(repo):
    chat = await repo.create_chat(owner_external_id="user-1", interface="cli")
    result = await repo.get_chat(chat.id)
    assert result is not None
    assert result.id == chat.id
    assert result.owner_external_id == "user-1"
    assert result.interface == "cli"


@pytest.mark.asyncio
async def test_messages_chronological_order(repo):
    chat = await repo.create_chat(owner_external_id="user-1", interface="cli")
    msg1 = ChatMessage(chat_id=chat.id, role="user", content="first")
    msg2 = ChatMessage(chat_id=chat.id, role="assistant", content="second")
    msg3 = ChatMessage(chat_id=chat.id, role="user", content="third")
    await repo.append_message(chat.id, msg1)
    await repo.append_message(chat.id, msg2)
    await repo.append_message(chat.id, msg3)

    messages = await repo.list_messages(chat.id)
    assert [m.content for m in messages] == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_list_messages_limit_returns_last_n(repo):
    chat = await repo.create_chat(owner_external_id="user-1", interface="cli")
    for i in range(5):
        await repo.append_message(
            chat.id, ChatMessage(chat_id=chat.id, role="user", content=f"msg-{i}")
        )

    messages = await repo.list_messages(chat.id, limit=3)
    assert len(messages) == 3
    assert [m.content for m in messages] == ["msg-2", "msg-3", "msg-4"]


@pytest.mark.asyncio
async def test_soft_delete_clears_history_new_messages_visible(repo):
    chat = await repo.create_chat(owner_external_id="user-1", interface="cli")
    await repo.append_message(chat.id, ChatMessage(chat_id=chat.id, role="user", content="old"))
    await repo.soft_delete_messages(chat.id)

    assert await repo.list_messages(chat.id) == []

    await repo.append_message(chat.id, ChatMessage(chat_id=chat.id, role="user", content="new"))
    messages = await repo.list_messages(chat.id)
    assert len(messages) == 1
    assert messages[0].content == "new"


@pytest.mark.asyncio
async def test_get_unknown_chat_returns_none(repo):
    result = await repo.get_chat(uuid4())
    assert result is None