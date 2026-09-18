"""Хэндлеры агентных команд: /research и /agent."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services.backend_client import BackendClient, BackendError
from bot.states import AgentFlow

router = Router()


@router.message(Command("research"))
async def cmd_research(message: Message, backend: BackendClient) -> None:
    """Мультиагент: researcher (RAG) + writer (цитирование)."""
    question = message.text.removeprefix("/research").strip()
    if not question:
        await message.answer("Использование: /research <вопрос>")
        return
    placeholder = await message.answer("⏳ Исследую...")
    try:
        answer = await backend.research(
            question=question,
            thread_id=f"tg-{message.chat.id}",
        )
        await placeholder.edit_text(answer)
    except BackendError as e:
        await placeholder.edit_text(str(e))
    except Exception:
        await placeholder.edit_text("Произошла ошибка. Попробуйте позже.")


@router.message(Command("agent"))
async def cmd_agent(message: Message, backend: BackendClient, state: FSMContext) -> None:
    """Персистентный агент с HIL: может остановиться перед отправкой письма."""
    text = message.text.removeprefix("/agent").strip()
    if not text:
        await message.answer("Использование: /agent <задача>")
        return
    placeholder = await message.answer("⏳ Думаю...")
    try:
        thread_id = f"agent-tg-{message.chat.id}"
        result = await backend.agent_chat(message=text, thread_id=thread_id)

        if result["status"] == "interrupted":
            preview = result.get("interrupt", {}).get("preview", {})
            preview_text = (
                f"📧 Агент хочет отправить письмо:\n\n"
                f"Кому: {preview.get('to', '?')}\n"
                f"Тема: {preview.get('subject', '?')}\n"
                f"Текст: {preview.get('body', '?')}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Отправить", callback_data="agent:approve"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="agent:reject"),
            ]])
            await placeholder.edit_text(preview_text, reply_markup=kb)
            await state.set_state(AgentFlow.waiting_for_approval)
            await state.update_data(thread_id=thread_id)
        else:
            await placeholder.edit_text(result.get("answer") or "Готово.")
    except BackendError as e:
        await placeholder.edit_text(str(e))
    except Exception:
        await placeholder.edit_text("Произошла ошибка. Попробуйте позже.")


@router.callback_query(AgentFlow.waiting_for_approval, F.data.in_({"agent:approve", "agent:reject"}))
async def on_agent_decision(callback: CallbackQuery, backend: BackendClient, state: FSMContext) -> None:
    data = await state.get_data()
    thread_id = data.get("thread_id", "")
    decision = callback.data == "agent:approve"
    await state.clear()

    try:
        result = await backend.agent_resume(thread_id=thread_id, decision=decision)
        text = result.get("answer") or ("Письмо отправлено." if decision else "Отправка отменена.")
        await callback.message.edit_text(text, reply_markup=None)
    except BackendError as e:
        await callback.message.edit_text(str(e), reply_markup=None)
    await callback.answer()