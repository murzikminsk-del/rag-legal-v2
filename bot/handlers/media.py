from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient, BackendError
from bot.web import stream_to_chat

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
    if not (name.endswith(".pdf") or name.endswith(".docx")):
        await message.answer("Поддерживаются только PDF и DOCX.")
        return
    if (doc.file_size or 0) > 10 * 1024 * 1024:
        await message.answer("Файл слишком большой, максимум 10 МБ.")
        return
    try:
        buf = BytesIO()
        await message.bot.download(doc, destination=buf)
        chat_id = await backend.get_or_create_chat(str(message.chat.id), "telegram")
        content = message.caption or f"[документ {doc.file_name}]"
        tokens = backend.send_message(chat_id, content, media=buf.getvalue(), mime=doc.mime_type or "application/octet-stream")
        await stream_to_chat(message, tokens)
    except BackendError as e:
        await message.answer(str(e))
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")