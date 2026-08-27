import time
from typing import AsyncIterator

from aiogram.types import Message

from bot.keyboards.inline import feedback_kb

try:
    import telegramify_markdown
    _HAS_TELEGRAMIFY = True
except ImportError:
    _HAS_TELEGRAMIFY = False

DEBOUNCE_MS = 700


def _render(text: str) -> tuple[str, str | None]:
    if _HAS_TELEGRAMIFY:
        return telegramify_markdown.markdownify(text), "MarkdownV2"
    return text, None


async def stream_to_chat(
    message: Message,
    events: AsyncIterator[dict],
    placeholder: Message | None = None,
) -> str:
    buffer = ""
    sent: Message | None = placeholder
    last_edit_at: float = time.monotonic() if placeholder is not None else 0.0
    message_saved = False

    async for event in events:
        if event["type"] == "token":
            buffer += event["delta"]
            now = time.monotonic()
            if sent is None:
                sent = await message.answer(buffer)
                last_edit_at = now
            elif (now - last_edit_at) * 1000 >= DEBOUNCE_MS:
                try:
                    await sent.edit_text(buffer)
                    last_edit_at = now
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

    if not message_saved and sent and buffer:
        try:
            await sent.edit_text(buffer)
        except Exception:
            pass

    return buffer