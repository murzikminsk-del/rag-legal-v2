import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import topics_kb
from bot.services.backend_client import BackendClient
from bot.states import AskFlow

router = Router()

TOPIC_LABELS = {
    "contracts": "Договоры и концессии",
    "compliance": "Комплаенс",
    "corporate": "Корпоративные документы",
    "lna": "ЛНА Группы",
}


@router.message(Command("ask"))
async def start_ask(message: Message, state: FSMContext) -> None:
    await message.answer("Выберите тему:", reply_markup=topics_kb())
    await state.set_state(AskFlow.waiting_for_topic)


@router.callback_query(AskFlow.waiting_for_topic, F.data.startswith("topic:"))
async def on_topic(callback: CallbackQuery, state: FSMContext) -> None:
    slug = callback.data.split(":", 1)[1]
    if slug == "cancel":
        await state.clear()
        await callback.message.edit_text("Сценарий отменён.")
    else:
        await state.update_data(topic=slug)
        await state.set_state(AskFlow.waiting_for_question)
        label = TOPIC_LABELS.get(slug, slug)
        await callback.message.edit_text(f"Тема: {label}\n\nВведите ваш вопрос:")
    await callback.answer()


@router.message(AskFlow.waiting_for_question, F.text)
async def on_question(message: Message, state: FSMContext, backend: BackendClient) -> None:
    data = await state.get_data()
    topic_label = TOPIC_LABELS.get(data["topic"], data["topic"])
    prompt = f"Тема: {topic_label}. Вопрос: {message.text}"
    await state.clear()

    try:
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        sent = None
        buffer = ""
        async for token in await backend.send_message(chat_id, prompt):
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
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")