from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def topics_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slug, label in [
        ("contracts", "📄 Договоры и концессии"),
        ("compliance", "✅ Комплаенс"),
        ("corporate", "🏛 Корпоративные документы"),
        ("lna", "📋 ЛНА Группы"),
    ]:
        builder.button(text=label, callback_data=f"topic:{slug}")
    builder.button(text="❌ Отмена", callback_data="topic:cancel")
    builder.adjust(1)
    return builder.as_markup()