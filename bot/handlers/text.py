import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient, BackendError
from bot.services.streaming import stream_to_chat

log = logging.getLogger(__name__)
router = Router()


async def _show_error(message: Message, placeholder: Message | None, text: str) -> None:
    """Показывает ошибку на месте «Думаю...», а если его нет — новым сообщением."""
    if placeholder is not None:
        try:
            await placeholder.edit_text(text)
            return
        except Exception:
            pass
    await message.answer(text)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await message.answer("Сначала завершите текущее действие кнопкой выше или отправьте /cancel.")
        return
    placeholder: Message | None = None
    try:
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        placeholder = await message.answer("⏳ Думаю...")
        events = backend.send_message(chat_id, message.text)
        await stream_to_chat(message, events, placeholder=placeholder)
    except BackendError as e:
        await _show_error(message, placeholder, str(e))
    except Exception:
        log.exception("handle_text failed")
        await _show_error(message, placeholder, "Произошла ошибка. Попробуйте позже.")