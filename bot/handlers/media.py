from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient, BackendError
from bot.web import stream_to_chat

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from bot.states import DocumentFlow

router = Router()


@router.message(F.photo)
async def handle_photo(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return
    photo = max(message.photo, key=lambda p: p.file_size or 0)
    if (photo.file_size or 0) > 2 * 1024 * 1024:
        await message.answer("Фото слишком большое, максимум 2 МБ.")
        return
    try:
        buf = BytesIO()
        await message.bot.download(photo, destination=buf)
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        content = message.caption or "[фото]"
        tokens = backend.send_message(chat_id, content, media=buf.getvalue(), mime="image/jpeg")
        await stream_to_chat(message, tokens)
    except BackendError as e:
        await message.answer(str(e))
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.message(F.voice)
async def handle_voice(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return
    try:
        buf = BytesIO()
        await message.bot.download(message.voice, destination=buf)
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        tokens = backend.send_message(chat_id, "[голосовое]", media=buf.getvalue(), mime="audio/ogg")
        await stream_to_chat(message, tokens)
    except BackendError as e:
        await message.answer(str(e))
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.message(F.document)
async def handle_document(message: Message, backend: BackendClient, state: FSMContext) -> None:
    if await state.get_state() is not None:
        return
    doc = message.document
    if not doc:
        return
    name = (doc.file_name or "").lower()
    if not (name.endswith(".pdf") or name.endswith(".docx") or name.endswith(".txt")):
        await message.answer("Поддерживаются PDF, DOCX и TXT.")
        return
    if (doc.file_size or 0) > 10 * 1024 * 1024:
        await message.answer("Файл слишком большой, максимум 10 МБ.")
        return
    try:
        buf = BytesIO()
        await message.bot.download(doc, destination=buf)
        buf.seek(0)

        if name.endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(buf) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        elif name.endswith(".docx"):
            from docx import Document
            docx = Document(buf)
            text = "\n".join(p.text for p in docx.paragraphs)
        else:
            text = buf.read().decode("utf-8", errors="ignore")

        text = text.strip()
        if not text:
            await message.answer("Не удалось извлечь текст из документа.")
            return

        await state.set_state(DocumentFlow.waiting_for_action)
        await state.update_data(doc_text=text[:12000], thread_id=f"doc-tg-{message.chat.id}")

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 Резюме", callback_data="doc:summarize"),
            InlineKeyboardButton(text="⚖️ Заключение", callback_data="doc:opinion"),
            InlineKeyboardButton(text="📝 Претензия", callback_data="doc:claim"),
        ]])
        await message.answer(
            f"Документ получен: {doc.file_name} ({len(text)} символов)\nЧто сделать?",
            reply_markup=kb,
        )
    except BackendError as e:
        await message.answer(str(e))
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.callback_query(DocumentFlow.waiting_for_action, F.data.in_({"doc:summarize", "doc:opinion", "doc:claim"}))
async def on_document_action(callback: CallbackQuery, backend: BackendClient, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("doc_text", "")
    thread_id = data.get("thread_id", "doc-default")
    await state.clear()

    action_map = {
        "doc:summarize": f"Резюмируй этот документ: {text}",
        "doc:opinion": f"Дай юридическое заключение: {text}",
        "doc:claim": f"Составь претензию на основе этого документа: {text}",
    }
    prompt = action_map[callback.data]

    await callback.message.edit_text("⏳ Обрабатываю...", reply_markup=None)
    try:
        result = await backend.agent_chat(message=prompt, thread_id=thread_id)
        answer = result.get("answer") or "Готово."
        await callback.message.edit_text(answer)
    except BackendError as e:
        await callback.message.edit_text(str(e))
    except Exception:
        await callback.message.edit_text("Произошла ошибка. Попробуйте позже.")
    await callback.answer()