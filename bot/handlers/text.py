import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return

    try:
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        sent = None
        buffer = ""
        async for token in await backend.send_message(chat_id, message.text):
            buffer += token
            if sent is None:
                sent = await message.answer(buffer)
            else:
                try:
                    await sent.edit_text(buffer)
                except Exception:
                    pass
        if sent and buffer:
            try:
                await sent.edit_text(buffer)
            except Exception:
                pass
    except (httpx.ConnectError, httpx.ReadTimeout):
        await message.answer("Не удалось подключиться к сервису. Попробуйте позже.")
    except httpx.HTTPStatusError as e:
        await message.answer(f"Ошибка сервиса: {e.response.status_code}. Попробуйте позже.")
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")