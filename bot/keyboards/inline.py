from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FEEDBACK_CB_PREFIX = "fb"
FEEDBACK_UP = "up"
FEEDBACK_DOWN = "down"


def feedback_kb(message_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👍", callback_data=f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_UP}:{message_id}")
    builder.button(text="👎", callback_data=f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_DOWN}:{message_id}")
    return builder.as_markup()

