"""Single-agent baseline: один create_agent с той же search_knowledge_base.

Tool search_knowledge_base — идентичен multi_agent_langgraph.py (тот же
_build_search_fn + _make_search_tool), чтобы сравнение было честным.
handoff_count всегда 0 — передач управления нет.

Запуск:
    uv run python -m experiments.single_agent_baseline
"""

import asyncio
import json
import time
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

# ── тестовые вопросы (те же, что в multi_agent_langgraph.py) ─────────────────

QUESTIONS = [
    "Каков размер неустойки за просрочку оплаты по договору поставки товара?",
    "Какие основания для досрочного расторжения трудового договора предусмотрены в кадровых документах?",
    "Какие условия конфиденциальности установлены в соглашении между юридическими лицами?",
    (
        "Если сотрудник нарушил политику информационной безопасности и это привело "
        "к разглашению коммерческой тайны — какие меры ответственности предусмотрены "
        "в документах компании?"
    ),
    "Каков порядок регистрации товарного знака в Роспатенте?",
]

# ── объединённый системный промпт (роли researcher + writer в одном агенте) ───

SINGLE_AGENT_PROMPT = (
    "Ты юридический ассистент. При ответе на вопрос:\n"
    "1. Используй инструмент search_knowledge_base для поиска фактов в корпусе документов.\n"
    "2. На основе найденных фактов составь связный ответ на русском языке.\n"
    "3. Цитируй источники в формате [1], [2] и т.д.\n"
    "4. Если ответа в базе нет — прямо об этом сообщи, не выдумывай факты."
)


# ── search tool: реальный RAG с fallback на мок ───────────────────────────────

def _build_search_fn():
    try:
        from app.services.rag import RAGService
        svc = RAGService()
        svc.build()

        async def _real(query: str) -> dict:
            return await asyncio.to_thread(svc.answer, query)

        print("[search] реальный RAG подключён")
        return _real
    except Exception as exc:
        print(f"[search] RAG недоступен ({exc}), используется мок")

        async def _mock(query: str) -> dict:
            return {
                "answer": (
                    f"По запросу «{query[:60]}» найдено: "
                    "неустойка 0.1% в день; срок расторжения — 14 дней уведомления; "
                    "конфиденциальность — 3 года после окончания договора."
                ),
                "sources": [
                    {"id": 1, "file_name": "Договор поставки товара.md", "score": 0.91},
                    {"id": 2, "file_name": "Соглашение о конфиденциальности между юридическими лицами.md", "score": 0.85},
                    {"id": 3, "file_name": "Политика информационной безопасности.md", "score": 0.78},
                ],
                "confident": True,
            }

        return _mock


def _make_search_tool(search_fn):
    @tool
    async def search_knowledge_base(query: str) -> str:
        """Ищет факты в корпусе юридических документов по текстовому запросу."""
        result = await search_fn(query)
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        if not sources:
            return answer or "По запросу ничего не найдено."
        cited = "; ".join(
            f"[{s.get('id')}] {s.get('file_name', '')}" for s in sources
        )
        return f"{answer}\nИсточники: {cited}"

    return search_knowledge_base


# ── сбор метрик ───────────────────────────────────────────────────────────────

def _collect_metrics(messages: list, elapsed_ms: float) -> dict:
    total_tokens = 0
    llm_calls = 0
    for msg in messages:
        if isinstance(msg, AIMessage):
            llm_calls += 1
            meta = getattr(msg, "usage_metadata", None) or {}
            total_tokens += meta.get("total_tokens", 0)
    return {
        "total_tokens": total_tokens,
        "llm_calls": llm_calls,
        "latency_ms": round(elapsed_ms),
        "handoff_count": 0,
    }


# ── основной прогон ───────────────────────────────────────────────────────────

async def main() -> None:
    settings = get_settings()
    model = ChatOpenAI(
        model=settings.llm.default_model,
        temperature=0,
        api_key=settings.llm.openai_api_key.get_secret_value(),
    )

    search_fn = _build_search_fn()
    search_tool = _make_search_tool(search_fn)

    from langchain.agents import create_agent

    graph = create_agent(
        model=model,
        tools=[search_tool],
        system_prompt=SINGLE_AGENT_PROMPT,
    )

    results: list[dict] = []

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n{'='*60}")
        print(f"Q{i}: {question}")

        t0 = time.perf_counter()
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": question}]},
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        messages = result.get("messages", [])

        final_answer = ""
        for msg in reversed(messages):
            content = getattr(msg, "content", "")
            if content and not getattr(msg, "tool_calls", None):
                final_answer = content
                break

        metrics = _collect_metrics(messages, elapsed_ms)
        print(f"--- финальный ответ ---\n{final_answer}")
        print(f"[метрики] токены={metrics['total_tokens']}  "
              f"llm_calls={metrics['llm_calls']}  "
              f"latency={metrics['latency_ms']}мс  "
              f"handoff={metrics['handoff_count']}")

        results.append({
            "impl": "single_agent",
            "question_id": f"Q{i}",
            "question": question,
            "answer": final_answer,
            **metrics,
        })

    results_path = Path("experiments/results.json")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding="utf-8"))
    existing = [r for r in existing if r.get("impl") != "single_agent"]
    existing.extend(results)
    results_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[результаты] сохранены → {results_path}")


if __name__ == "__main__":
    asyncio.run(main())