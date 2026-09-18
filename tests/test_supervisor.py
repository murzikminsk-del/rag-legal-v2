"""Структурные тесты supervisor-графа (researcher + writer).

Проверяют сборку, состав узлов и базовую маршрутизацию
без реального LLM и без Qdrant.
"""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr


# ── заглушка LLM ──────────────────────────────────────────────────────────────

class FakeChat(BaseChatModel):
    responses: list[AIMessage]
    _idx: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """Supervisor вызывает bind_tools — возвращаем self, инструменты игнорируем."""
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop=None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        resp = self.responses[min(self._idx, len(self.responses) - 1)]
        self._idx += 1
        return ChatResult(generations=[ChatGeneration(message=resp)])


# ── вспомогательная сборка графа ──────────────────────────────────────────────

def _make_graph(model: BaseChatModel):
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph_supervisor import create_supervisor

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Ищет факты в корпусе юридических документов."""
        return f"Факты по запросу «{query}»: неустойка 0.1% в день [1]."

    researcher = create_agent(
        model=model,
        tools=[search_knowledge_base],
        name="researcher",
        system_prompt="Найди факты. Финальный ответ НЕ пиши.",
    )
    writer = create_agent(
        model=model,
        tools=[],
        name="writer",
        system_prompt="Собери ответ с цитированием [1], [2].",
    )
    workflow = create_supervisor(
        agents=[researcher, writer],
        model=model,
        prompt="Сначала researcher, затем writer.",
        output_mode="last_message",
    )
    return workflow.compile(checkpointer=InMemorySaver())


# ── тесты ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_supervisor_graph_compiles():
    """Граф собирается без исключений."""
    model = FakeChat(responses=[AIMessage(content="ok", id="ai-1")])
    graph = _make_graph(model)
    assert graph is not None


@pytest.mark.asyncio
async def test_supervisor_graph_has_expected_nodes():
    """Граф содержит узлы researcher и writer."""
    model = FakeChat(responses=[AIMessage(content="ok", id="ai-1")])
    graph = _make_graph(model)
    nodes = set(graph.get_graph(xray=True).nodes.keys())
    assert any(n.startswith("researcher") for n in nodes), f"нет узла researcher: {nodes}"
    assert any(n.startswith("writer") for n in nodes), f"нет узла writer: {nodes}"


@pytest.mark.asyncio
async def test_supervisor_returns_nonempty_answer():
    """Граф принимает вопрос и возвращает непустой список сообщений."""
    sup_handoff = AIMessage(
        content="",
        id="ai-s1",
        tool_calls=[{
            "name": "transfer_to_researcher",
            "args": {},
            "id": "tc-1",
            "type": "tool_call",
        }],
    )
    res_tool_call = AIMessage(
        content="",
        id="ai-r1",
        tool_calls=[{
            "name": "search_knowledge_base",
            "args": {"query": "неустойка"},
            "id": "tc-2",
            "type": "tool_call",
        }],
    )
    res_facts = AIMessage(content="Факты: неустойка 0.1% [1].", id="ai-r2")
    sup_handoff2 = AIMessage(
        content="",
        id="ai-s2",
        tool_calls=[{
            "name": "transfer_to_writer",
            "args": {},
            "id": "tc-3",
            "type": "tool_call",
        }],
    )
    writer_ans = AIMessage(
        content="Неустойка за просрочку составляет 0,1% в день [1].",
        id="ai-w1",
    )
    sup_finish = AIMessage(content="Готово.", id="ai-s3")

    model = FakeChat(responses=[
        sup_handoff, res_tool_call, res_facts,
        sup_handoff2, writer_ans, sup_finish,
    ])
    graph = _make_graph(model)
    result = await graph.ainvoke(
        {"messages": [HumanMessage("Каков размер неустойки?")]},
        {"configurable": {"thread_id": "test-output"}},
    )
    messages = result.get("messages", [])
    assert len(messages) > 0
    assert any(getattr(m, "content", "") for m in messages)