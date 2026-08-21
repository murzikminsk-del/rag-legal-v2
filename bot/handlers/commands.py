import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient

log = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, backend: BackendClient) -> None:
    try:
        await backend.get_or_create_chat(str(message.chat.id), "telegram")
        await message.answer(
            f"Добрый день! Я юридический ассистент.\n\n"
            "Задайте вопрос напрямую — отвечу на него.\n"
            "/ask — выбрать тему для запроса\n"
            "/clear — начать диалог заново\n"
            "/help — список команд"
        )
    except Exception:
        log.exception("cmd_start failed")
        await message.answer("Не удалось подключиться к сервису. Попробуйте позже.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Доступные команды:\n\n"
        "/start — начать работу\n"
        "/ask — задать вопрос по теме (договоры, комплаенс и др.)\n"
        "/clear — очистить историю диалога\n"
        "/cancel — отменить текущий сценарий\n"
        "/help — эта справка"
    )


@router.message(Command("clear"))
async def cmd_clear(message: Message, backend: BackendClient) -> None:
    try:
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        await backend.clear_messages(chat_id)
        await message.answer("История очищена. Можете задать новый вопрос.")
    except Exception:
        await message.answer("Не удалось очистить историю. Попробуйте позже.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять — вы не в активном сценарии.")
        return
    await state.clear()
    await message.answer("Сценарий отменён.")