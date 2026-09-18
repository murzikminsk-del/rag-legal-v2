"""Live-демо потока supervisor → researcher → writer.

Запуск: uv run python -m scripts.multi_agent_demo
Нужен LLM__OPENAI_API_KEY в .env и запущенный Qdrant (или mock-fallback).
"""

import asyncio
import os
import time

from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    import httpx
    from langchain_openai import ChatOpenAI

    from app.agents.supervisor import build_supervisor

    model = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.environ["LLM__OPENAI_API_KEY"],
    )

    async def mock_search(query: str) -> dict:
        return {
            "answer": f"Факты по запросу «{query}»: согласно корпусу, срок — 30 дней [1].",
            "sources": [{"id": 1, "file_name": "договор_аренды.md"}],
            "confident": True,
        }

    graph = build_supervisor(model, mock_search)
    question = "Каков срок возврата денег за подписку? Ответь с источниками."
    print(f"Вопрос: {question}\n")

    t0 = time.perf_counter()
    async for chunk in graph.astream(
        {"messages": [{"role": "user", "content": question}]},
        {"configurable": {"thread_id": "demo"}},
        stream_mode="updates",
    ):
        for node_name in chunk:
            print(f"  → {node_name}")

    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
        {"configurable": {"thread_id": "demo-final"}},
    )
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"\nОтвет ({elapsed:.0f} мс):\n{result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(main())