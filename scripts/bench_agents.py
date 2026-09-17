# scripts/bench_agents.py
"""Бенчмарк: naive (B6.2) vs custom LangGraph vs prebuilt — 5 задач × 3 прогона."""

import asyncio
import time
from pathlib import Path

import httpx
from openai import OpenAI

from app.core.config import get_settings
from app.services.agent_naive import run_agent as run_naive

TASKS = [
    {"id": 1, "tag": "time",        "question": "Какое сейчас время в Москве?"},
    {"id": 2, "tag": "search",      "question": "Найди в базе знаний условия расторжения концессионного соглашения."},
    {"id": 3, "tag": "chain",       "question": "Найди в базе знаний норму о сроках исковой давности и отправь результат в Telegram чат 111222333."},
    {"id": 4, "tag": "time+search", "question": "Узнай текущую дату и проверь: не истёк ли срок исковой давности (3 года) для договора, заключённого 1 января 2022 года?"},
    {"id": 5, "tag": "no-tool",     "question": "Сколько будет 15 умножить на 27?"},
]
RUNS = 3


def _sum_usage(state: dict) -> tuple[int, int]:
    prompt = completion = 0
    for msg in state.get("messages", []):
        meta = getattr(msg, "usage_metadata", None)
        if meta:
            prompt += meta.get("input_tokens", 0)
            completion += meta.get("output_tokens", 0)
    return prompt, completion


def bench_naive(question: str) -> dict:
    s = get_settings()
    client = OpenAI(
        api_key=s.llm.openai_api_key.get_secret_value(),
        http_client=httpx.Client(trust_env=False),
    )
    t0 = time.perf_counter()
    result = run_naive(question, max_steps=10, client=client)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    prompt = sum(e.get("llm_input_tokens") or 0 for e in result.get("trace", []))
    completion = sum(e.get("llm_output_tokens") or 0 for e in result.get("trace", []))
    return {"latency_ms": latency_ms, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_steps": result.get("steps", 0)}


async def bench_custom(question: str, task_id: int = 0) -> dict:
    from app.services.agent_graph import custom_graph
    t0 = time.perf_counter()
    state = await custom_graph.ainvoke(
        {"messages": [{"role": "user", "content": question}],
         "iteration_count": 0, "tool_results": []},
        config={"configurable": {"thread_id": f"bench-{task_id}"}},
    )
    latency_ms = round((time.perf_counter() - t0) * 1000)
    prompt, completion = _sum_usage(state)
    return {"latency_ms": latency_ms, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_steps": state.get("iteration_count", 0)}


async def bench_prebuilt(question: str) -> dict:
    from app.services.agent_graph import prebuilt_graph
    t0 = time.perf_counter()
    state = await prebuilt_graph.ainvoke(
        {"messages": [{"role": "user", "content": question}]},
    )
    latency_ms = round((time.perf_counter() - t0) * 1000)
    prompt, completion = _sum_usage(state)
    steps = sum(1 for m in state.get("messages", [])
                if getattr(m, "type", "") == "ai")
    return {"latency_ms": latency_ms, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_steps": steps}


async def main() -> None:
    rows: list[dict] = []

    for task in TASKS:
        print(f"\n=== [{task['id']}] {task['tag']} ===")
        for impl in ("naive", "custom", "prebuilt"):
            lats, prompts, completions, steps_list = [], [], [], []
            for run in range(1, RUNS + 1):
                print(f"  {impl} run {run}/{RUNS}...", end=" ", flush=True)
                try:
                    if impl == "naive":
                        r = bench_naive(task["question"])
                    elif impl == "custom":
                        r = await bench_custom(task["question"], task_id=task["id"])
                    else:
                        r = await bench_prebuilt(task["question"])
                    lats.append(r["latency_ms"])
                    prompts.append(r["prompt_tokens"])
                    completions.append(r["completion_tokens"])
                    steps_list.append(r["total_steps"])
                    print(f"{r['latency_ms']}ms / {r['prompt_tokens']}+{r['completion_tokens']}tok")
                except Exception as exc:
                    print(f"ERROR: {exc}")
                    lats.append(0); prompts.append(0); completions.append(0); steps_list.append(0)

            rows.append({
                "task_id": task["id"], "tag": task["tag"], "impl": impl,
                "latency_ms": round(sum(lats) / len(lats)),
                "prompt_tokens": round(sum(prompts) / len(prompts)),
                "completion_tokens": round(sum(completions) / len(completions)),
                "total_steps": round(sum(steps_list) / len(steps_list), 1),
            })

    docs = Path(__file__).parent.parent / "docs"
    docs.mkdir(exist_ok=True)
    lines = [
        "# Бенчмарк: naive (B6.2) vs custom LangGraph vs prebuilt\n",
        "| # | Задача | Реализация | latency_ms | prompt_tokens | completion_tokens | total_steps |",
        "|---|--------|------------|------------|---------------|-------------------|-------------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['task_id']} | {r['tag']} | {r['impl']} | {r['latency_ms']} | "
            f"{r['prompt_tokens']} | {r['completion_tokens']} | {r['total_steps']} |"
        )
    report = docs / "agent-graph-report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nОтчёт: {report}")


if __name__ == "__main__":
    asyncio.run(main())