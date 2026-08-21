from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.fsm import on_topic, start_ask
from bot.states import AskFlow


@pytest.mark.asyncio
async def test_start_ask_sets_state():
    message = MagicMock()
    message.answer = AsyncMock()
    state = AsyncMock()

    await start_ask(message, state)

    message.answer.assert_called_once()
    state.set_state.assert_called_once_with(AskFlow.waiting_for_topic)


@pytest.mark.asyncio
async def test_on_topic_stores_topic_and_transitions():
    callback = MagicMock()
    callback.data = "topic:contracts"
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()

    await on_topic(callback, state)

    state.update_data.assert_called_once_with(topic="contracts")
    state.set_state.assert_called_once_with(AskFlow.waiting_for_question)


@pytest.mark.asyncio
async def test_on_topic_cancel_clears_state():
    callback = MagicMock()
    callback.data = "topic:cancel"
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    state = AsyncMock()

    await on_topic(callback, state)

    state.clear.assert_called_once()
    state.set_state.assert_not_called()