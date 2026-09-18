"""Инструменты агента.

`multiply` — простой самодостаточный инструмент.
`build_search_knowledge_base` — RAG как инструмент: поиск инжектируется
как async-callable, чтобы легко подменялся в тестах.
"""

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, tool


@tool
def multiply(a: int, b: int) -> int:
    """Перемножает два целых числа. Вызывать для любого умножения."""
    return a * b


def build_search_knowledge_base(
    search_fn: Callable[[str], Awaitable[dict]],
) -> BaseTool:
    """Собирает инструмент поиска по базе знаний поверх переданного search_fn.

    search_fn(query) возвращает {answer, sources[{id, file_name, ...}], confident}.
    """

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Ищет ответ в корпоративной базе юридических знаний по текстовому запросу.

        Вызывать когда нужен факт из договоров, НПА или корпоративных документов.
        Не вызывать для арифметики или общих знаний.
        """
        result = await search_fn(query)
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        if not sources:
            return answer
        cited = "; ".join(
            f"[{s.get('id')}] {s.get('file_name', '')}".strip() for s in sources
        )
        return f"{answer}\nИсточники: {cited}"

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
    
def build_legal_opinion(llm) -> BaseTool:
    """Инструмент составления юридического заключения."""

    @tool
    async def legal_opinion(situation: str) -> str:
        """Составляет краткое юридическое заключение по описанной ситуации.

        Вызывать когда пользователь просит правовую оценку, юридическое мнение
        или анализ ситуации с точки зрения закона.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(
                content=(
                    "Ты опытный юрист. Дай краткое юридическое заключение строго в формате:\n"
                    "**Факты:** (краткое изложение ситуации)\n"
                    "**Применимое право:** (статьи законов, нормы)\n"
                    "**Анализ:** (правовая оценка)\n"
                    "**Вывод:** (итоговое мнение)\n"
                    "**Рекомендации:** (что делать)"
                )
            ),
            HumanMessage(content=f"Ситуация:\n\n{situation}"),
        ]
        response = await llm.ainvoke(messages)
        return response.content

    return legal_opinion