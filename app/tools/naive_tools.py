# app/tools/naive_tools.py
"""Инструменты наивного агента: реализации + описания в JSON Schema."""

from datetime import datetime
from zoneinfo import ZoneInfo


def search_knowledge_base(query: str) -> str:
    """Поиск top-1 фрагмента в векторной базе знаний юридических документов."""
    try:
        from app.services.rag import get_rag_service
        svc = get_rag_service()
        svc.build()
        result = svc.retrieve_context(query)
        if not result:
            return "По запросу ничего не найдено в базе знаний."
        return result.split("---")[0].strip()
    except Exception as exc:
        return f"Ошибка поиска в базе знаний: {exc}"


def get_current_time(timezone: str = "Europe/Moscow") -> str:
    """Текущие дата и время в указанном часовом поясе в формате ISO 8601."""
    return datetime.now(ZoneInfo(timezone)).isoformat()


def send_telegram_message(chat_id: str, text: str) -> str:
    """Отправка сообщения клиенту в Telegram (заглушка — только print)."""
    print(f"[TELEGRAM → {chat_id}] {text}")
    return f"Сообщение отправлено в {chat_id}"


DISPATCH = {
    "search_knowledge_base": search_knowledge_base,
    "get_current_time": get_current_time,
    "send_telegram_message": send_telegram_message,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Ищет информацию в векторной базе знаний юридических документов проекта: "
                "договоры, концессии, нормативные правила, условия соглашений. "
                "Вызывай, когда нужно найти конкретный факт, правовую норму или "
                "условие из индексированного корпуса документов."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском языке",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Возвращает текущие дату и время в указанном часовом поясе "
                "в формате ISO 8601. Вызывай, когда задача требует знания "
                "текущей даты или времени, например для расчёта сроков."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Имя часового пояса IANA, например Europe/Moscow",
                        "default": "Europe/Moscow",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_telegram_message",
            "description": (
                "Отправляет текстовое сообщение клиенту в Telegram по идентификатору чата. "
                "Вызывай только после того, как финальный ответ уже сформирован и "
                "пользователь явно указал chat_id получателя."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "Идентификатор чата клиента в Telegram",
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст сообщения для клиента",
                    },
                },
                "required": ["chat_id", "text"],
            },
        },
    },
]