import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.chat.domain import Chat, ChatMessage
from app.chat.service import ChatService, KEEP_RECENT


def _make_llm_mock(summary_text: str = "summary") -> MagicMock:
    choice = MagicMock()
    choice.message.content = summary_text
    completion = MagicMock()
    completion.choices = [choice]
    llm = MagicMock()
    llm.chat.completions.create = AsyncMock(return_value=completion)
    return llm


def make_service(llm=None) -> ChatService:
    repo = AsyncMock()
    return ChatService(repository=repo, llm=llm or MagicMock())


def make_messages(n: int) -> list[ChatMessage]:
    chat_id = uuid4()
    return [
        ChatMessage(chat_id=chat_id, role="user", content=f"msg-{i}", tokens=10)
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_few_messages_no_summary():
    msgs = make_messages(KEEP_RECENT)
    svc = make_service()
    context = await svc._build_context(chat=None, history=msgs)
    assert len(context) == KEEP_RECENT
    assert all(m["role"] in ("user", "assistant", "system") for m in context)


@pytest.mark.asyncio
async def test_few_messages_no_llm_call():
    msgs = make_messages(KEEP_RECENT)
    llm = _make_llm_mock()
    svc = make_service(llm=llm)
    await svc._build_context(chat=None, history=msgs)
    llm.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_many_messages_triggers_summary():
    msgs = make_messages(KEEP_RECENT + 5)
    llm = _make_llm_mock("краткое содержание")
    svc = make_service(llm=llm)
    context = await svc._build_context(chat=None, history=msgs)
    llm.chat.completions.create.assert_called_once()
    assert any("краткое содержание" in m["content"] for m in context)


@pytest.mark.asyncio
async def test_recent_messages_preserved_after_summary():
    msgs = make_messages(KEEP_RECENT + 5)
    llm = _make_llm_mock("summary")
    svc = make_service(llm=llm)
    context = await svc._build_context(chat=None, history=msgs)
    contents = [m["content"] for m in context]
    assert f"msg-{KEEP_RECENT + 4}" in contents
    assert f"msg-{KEEP_RECENT}" in contents


@pytest.mark.asyncio
async def test_system_prompt_prepended():
    chat = Chat(owner_external_id="u1", interface="cli", system_prompt="Ты юридический ассистент")
    msgs = make_messages(3)
    svc = make_service()
    context = await svc._build_context(chat=chat, history=msgs)
    assert context[0]["role"] == "system"
    assert "юридический" in context[0]["content"]
