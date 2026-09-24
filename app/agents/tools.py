"""Инструменты агента.

`build_search_knowledge_base` — RAG как инструмент: поиск инжектируется
как async-callable, чтобы легко подменялся в тестах.
"""

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, tool


def build_search_knowledge_base(
    search_fn: Callable[[str], Awaitable[str]],
) -> BaseTool:
    """Собирает инструмент поиска по базе знаний поверх переданного search_fn.

    search_fn(query) возвращает пронумерованные фрагменты документов или ''.
    """

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Ищет фрагменты в базе юридических документов: договоры, концессии, ЛНА.

        Вызывать для любого вопроса о содержании документов. query — самостоятельный
        поисковый запрос на русском; если известен договор или регион — укажи его в запросе.
        """
        context = await search_fn(query)
        return context or "В базе ничего не найдено по этому запросу."

    return search_knowledge_base


def build_summarize_document(llm) -> BaseTool:
    """Инструмент структурированного анализа текста документа."""

    @tool
    async def summarize_document(text: str) -> str:
        """Анализирует текст юридического документа и возвращает структурированное резюме.

        Вызывать когда пользователь просит резюмировать, проанализировать или
        кратко изложить содержание документа.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(
                content=(
                    "Ты юридический аналитик. Проанализируй документ и верни "
                    "структурированное резюме строго в формате:\n"
                    "**Стороны:** ...\n"
                    "**Предмет:** ...\n"
                    "**Ключевые обязательства:** ...\n"
                    "**Сроки:** ...\n"
                    "**Риски и важные условия:** ..."
                )
            ),
            HumanMessage(content=f"Документ:\n\n{text}"),
        ]
        response = await llm.ainvoke(messages)
        return response.content

    return summarize_document


@tool
def format_claim(
    claimant: str,
    respondent: str,
    subject: str,
    amount: str,
    grounds: str,
) -> str:
    """Составляет текст претензии по переданным параметрам.

    claimant — истец (название, адрес).
    respondent — ответчик (название, адрес).
    subject — предмет претензии (что нарушено).
    amount — сумма требований.
    grounds — правовые основания (статьи, пункты договора).
    """
    from datetime import date

    today = date.today().strftime("%d.%m.%Y")
    return (
        f"ПРЕТЕНЗИЯ\n\n"
        f"От: {claimant}\n"
        f"Кому: {respondent}\n"
        f"Дата: {today}\n\n"
        f"Уважаемые коллеги,\n\n"
        f"Настоящим уведомляем вас о нарушении: {subject}.\n\n"
        f"Правовые основания: {grounds}.\n\n"
        f"На основании изложенного требуем в течение 30 (тридцати) календарных дней "
        f"с момента получения настоящей претензии выплатить сумму в размере {amount}.\n\n"
        f"В случае неисполнения требования в установленный срок оставляем за собой "
        f"право обратиться в суд за защитой нарушенных прав.\n\n"
        f"С уважением,\n{claimant}"
    )