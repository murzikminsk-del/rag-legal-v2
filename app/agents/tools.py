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