from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.inline import FEEDBACK_CB_PREFIX, FEEDBACK_DOWN, FEEDBACK_UP
from bot.services.backend_client import BackendClient, BackendError

router = Router()


@router.callback_query(F.data.startswith(FEEDBACK_CB_PREFIX + ":"))
async def handle_feedback(cb: CallbackQuery, backend: BackendClient) -> None:
    parts = (cb.data or "").split(":", 2)
    if len(parts) != 3:
        await cb.answer("Ошибка формата")
        return
    _, vote, message_id = parts
    if vote not in (FEEDBACK_UP, FEEDBACK_DOWN):
        await cb.answer("Неизвестная оценка")
        return

    chat_id = await backend.get_or_create_chat(str(cb.message.chat.id), "telegram")
    try:
        await backend.post_feedback(chat_id, message_id, vote)
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("Спасибо!" if vote == FEEDBACK_UP else "Учтём.")
    except BackendError as e:
        await cb.answer(str(e))
    except Exception:
        await cb.answer("Ошибка при сохранении отзыва")