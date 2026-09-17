# app/services/agent_graph.py
import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

import httpx
from langchain_core.messages import ToolMessage

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iteration_count: int
    tool_results: Annotated[list[dict], operator.add]
    

@tool
def get_current_time(timezone: str = "Europe/Moscow") -> str:
    """Возвращает текущую дату и время в указанном часовом поясе (ISO 8601).
    Вызывать когда задача требует знания текущей даты: расчёт сроков, дедлайны."""
    return datetime.now(ZoneInfo(timezone)).isoformat()


@tool
def search_knowledge_base(query: str) -> str:
    """Ищет информацию в базе знаний юридических документов по текстовому запросу.
    Вызывать когда нужен факт, правовая норма или условие из договоров и НПА."""
    try:
        from app.services.rag import get_rag_service
        svc = get_rag_service()
        svc.build()
        result = svc.retrieve_context(query)
        return result.split("---")[0].strip() if result else "По запросу ничего не найдено."
    except Exception as exc:
        return f"Ошибка поиска в базе знаний: {exc}"


@tool
def send_telegram_message(chat_id: str, text: str) -> str:
    """Отправляет уведомление клиенту в Telegram по идентификатору чата.
    Вызывать только после формирования финального ответа, если пользователь указал chat_id."""
    print(f"[TELEGRAM → {chat_id}] {text}")
    return f"Сообщение отправлено в {chat_id}"


TOOLS = [get_current_time, search_knowledge_base, send_telegram_message]

MAX_ITERATIONS = 6

_s = get_settings()
_model = ChatOpenAI(
    model=_s.llm.default_model,
    temperature=0,
    api_key=_s.llm.openai_api_key.get_secret_value(),
    http_async_client=httpx.AsyncClient(trust_env=False),
)
_bound_model = _model.bind_tools(TOOLS)
_tool_by_name: dict = {t.name: t for t in TOOLS}


async def call_model(state: AgentState) -> dict:
    response = await _bound_model.ainvoke(state["messages"])
    return {"messages": [response], "iteration_count": state["iteration_count"] + 1}


async def execute_tool(state: AgentState) -> dict:
    last = state["messages"][-1]
    messages: list = []
    results: list[dict] = []
    for call in last.tool_calls:
        if call["name"] not in _tool_by_name:
            content = f"error: unknown tool '{call['name']}'"
        else:
            content = str(await _tool_by_name[call["name"]].ainvoke(call["args"]))
        messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
        results.append({"name": call["name"], "args": call["args"], "result": content})
    return {"messages": messages, "tool_results": results}


async def force_finish(state: AgentState) -> dict:
    return {}


def route_after_model(state: AgentState) -> Literal["execute_tool", "force_finish"]:
    if state["iteration_count"] >= MAX_ITERATIONS:
        return "force_finish"
    last = state["messages"][-1]
    return "execute_tool" if getattr(last, "tool_calls", None) else "force_finish"


builder = StateGraph(AgentState)
builder.add_node("call_model", call_model)
builder.add_node("execute_tool", execute_tool)
builder.add_node("force_finish", force_finish)
builder.add_edge(START, "call_model")
builder.add_conditional_edges(
    "call_model",
    route_after_model,
    {"execute_tool": "execute_tool", "force_finish": "force_finish"},
)
builder.add_edge("execute_tool", "call_model")
builder.add_edge("force_finish", END)

custom_graph = builder.compile()

_SYSTEM_PROMPT = (
    "Ты юридический ассистент. Помогай разбираться в документах, договорах и "
    "нормативных актах. Используй инструменты когда нужна информация из базы знаний, "
    "текущая дата или отправка уведомлений. Отвечай точно и ссылайся только на то, "
    "что вернули инструменты."
)

from langchain.agents import create_agent  # LangChain 1.0: рекомендуемый путь

prebuilt_graph = create_agent(
    model=_model,
    tools=TOOLS,
    system_prompt=_SYSTEM_PROMPT,
)

