from typing import AsyncIterator

from aiogram.types import Message

from bot.keyboards.inline import feedback_kb

try:
    import telegramify_markdown
    _HAS_TELEGRAMIFY = True
except ImportError:
    _HAS_TELEGRAMIFY = False

EDIT_EVERY = 30


def _render(text: str) -> tuple[str, str | None]:
    if _HAS_TELEGRAMIFY:
        return telegramify_markdown.markdownify(text), "MarkdownV2"
    return text, None


async def stream_to_chat(
    message: Message,
    events: AsyncIterator[dict],
) -> str:
    buffer = ""
    sent = None
    last_edit_len = 0
    message_saved = False  # финальный render уже сделан — flush не нужен

    async for event in events:
        if event["type"] == "token":
            buffer += event["delta"]
            if sent is None:
                sent = await message.answer(buffer)
                last_edit_len = len(buffer)
            elif len(buffer) - last_edit_len >= EDIT_EVERY:
                try:
                    await sent.edit_text(buffer)
                    last_edit_len = len(buffer)
                except Exception:
                    pass

        elif event["type"] == "message_saved":
            message_saved = True
            message_id = event["message_id"]
            if sent:
                rendered, parse_mode = _render(buffer)
                try:
                    await sent.edit_text(
                        rendered,
                        reply_markup=feedback_kb(message_id),
                        parse_mode=parse_mode,
                    )
                except Exception:
                    try:
                        await sent.edit_reply_markup(reply_markup=feedback_kb(message_id))
                    except Exception:
                        pass

    # flush только если message_saved не пришёл (ошибка на сервере)
    if not message_saved and sent and buffer and len(buffer) > last_edit_len:
        try:
            await sent.edit_text(buffer)
        except Exception:
            pass

    return buffer