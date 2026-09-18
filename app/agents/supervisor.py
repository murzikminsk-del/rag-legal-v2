"""Мультиагентный супервизор: researcher (RAG) + writer (цитирование).

researcher собирает факты через search_knowledge_base (RAG),
writer оформляет финальный ответ с цитированием [1], [2].
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.tools import build_search_knowledge_base

RESEARCHER_PROMPT = (
    "Ты исследователь. Найди факты по вопросу через инструмент "
    "search_knowledge_base и верни маркированный список фактов с источниками. "
    "НЕ пиши финальный ответ пользователю — этим занимается writer."
)
WRITER_PROMPT = (
    "Ты редактор. Получаешь список фактов от researcher и собираешь связный "
    "ответ на русском с цитированием источников в формате [1], [2]. "
    "Если фактов не хватает — попроси супервизора вернуть запрос researcher."
)
SUPERVISOR_PROMPT = (
    "Ты супервизор команды из researcher и writer. Сначала ВСЕГДА передавай "
    "задачу researcher для сбора фактов, затем writer — для финального ответа. "
    "Сам не отвечай пользователю, только делегируй."
)


def build_supervisor(
    model: BaseChatModel,
    search_fn: Callable[[str], Awaitable[dict]],
    checkpointer: Any = None,
):
    """Собирает и компилирует supervisor-граф из researcher (RAG) и writer.

    search_fn(query) — тот же контракт RAG-сервиса, что у одиночного агента.
    """
    from langchain.agents import create_agent
    from langgraph_supervisor import create_supervisor

    researcher = create_agent(
        model=model,
        tools=[build_search_knowledge_base(search_fn)],
        name="researcher",
        system_prompt=RESEARCHER_PROMPT,
    )
    writer = create_agent(
        model=model,
        tools=[],
        name="writer",
        system_prompt=WRITER_PROMPT,
    )
    workflow = create_supervisor(
        agents=[researcher, writer],
        model=model,
        prompt=SUPERVISOR_PROMPT,
        output_mode="last_message",
    )
    return workflow.compile(checkpointer=checkpointer or InMemorySaver())