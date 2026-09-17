# scripts/run_comparison.py
"""Прогон 5 задач на agent_naive и agent_react для сравнения."""

import logging

from app.services.agent_naive import run_agent as naive_run
from app.services.agent_react import run_agent as react_run

logging.basicConfig(level=logging.WARNING)

TASKS = [
    {
        "id": 1,
        "category": "simple",
        "desc": "Текущее время",
        "question": "Какое сейчас время в Москве?",
    },
    {
        "id": 2,
        "category": "simple",
        "desc": "Поиск по базе знаний",
        "question": "Найди в базе знаний условия расторжения концессионного соглашения.",
    },
    {
        "id": 3,
        "category": "medium",
        "desc": "Поиск + Telegram (composability)",
        "question": (
            "Найди в базе знаний норму о сроках исковой давности "
            "и отправь результат в Telegram чат 111222333."
        ),
    },
    {
        "id": 4,
        "category": "medium",
        "desc": "Время + поиск срока (composability)",
        "question": (
            "Узнай текущую дату и проверь: не истёк ли срок исковой давности "
            "(3 года) для договора, заключённого 1 января 2022 года?"
        ),
    },
    {
        "id": 5,
        "category": "provocative",
        "desc": "Арифметика — без tools",
        "question": "Сколько будет 15 умножить на 27?",
    },
]


def naive_tokens(result: dict) -> int:
    return sum(
        (e.get("llm_input_tokens") or 0) + (e.get("llm_output_tokens") or 0)
        for e in result.get("trace", [])
    )


def main():
    print("=" * 65)
    print("Сравнение agent_naive vs agent_react")
    print("=" * 65)

    for task in TASKS:
        print(f"\n[{task['id']}] {task['category'].upper()} — {task['desc']}")
        print(f"Q: {task['question']}")

        naive = naive_run(task["question"], max_steps=10)
        n_tokens = naive_tokens(naive)
        print(f"  naive : шагов={naive['steps']}, tokens≈{n_tokens}")
        print(f"  naive : {str(naive.get('answer', ''))[:120]}")

        react = react_run(task["question"], max_iterations=10)
        r_tokens = react["usage"]["total"]
        print(f"  react : шагов={react['steps']}, tokens={r_tokens}, ревизий={react['revisions']}")
        print(f"  react : {str(react.get('answer', ''))[:120]}")

    print("\n" + "=" * 65)
    print("Готово. Заполни docs/agent-react-report.md по этим данным.")


if __name__ == "__main__":
    main()