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


def topics_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Договоры и концессии", callback_data="topic:contracts")
    builder.button(text="Комплаенс", callback_data="topic:compliance")
    builder.button(text="Корпоративные документы", callback_data="topic:corporate")
    builder.button(text="ЛНА Группы", callback_data="topic:lna")
    builder.button(text="Отмена", callback_data="topic:cancel")
    builder.adjust(1)
    return builder.as_markup()