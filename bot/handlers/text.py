from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient, BackendError
from bot.web import stream_to_chat

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return
    try:
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        tokens = backend.send_message(chat_id, message.text)
        await stream_to_chat(message, tokens)
    except BackendError as e:
        await message.answer(str(e))
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")