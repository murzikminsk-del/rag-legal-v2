"""Прогон 20 запросов через RAG для наполнения Phoenix трейсами.

Запуск (пока Docker поднят):
    uv run python scripts/send_test_queries.py
"""

import asyncio
import json
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"

GOLDEN = json.loads(Path("tests/eval/golden_dataset.json").read_text(encoding="utf-8"))
EXTRA = [
    "Что такое концессионное соглашение?",
    "Как расторгнуть договор аренды досрочно?",
    "Какие документы нужны для регистрации договора аренды в Росреестре?",
    "Что такое неустойка и как она рассчитывается?",
    "Какова ответственность за нарушение конфиденциальности персональных данных?",
]

QUESTIONS = [item["user_input"] for item in GOLDEN[:15]] + EXTRA


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60, trust_env=False) as client:
        for i, question in enumerate(QUESTIONS, 1):
            print(f"[{i:02d}/20] {question[:70]}…")
            try:
                r = await client.post("/rag/query", json={"question": question})
                data = r.json()
                confident = data.get("confident", "?")
                score = data.get("top_score", 0)
                print(f"        confident={confident}  score={score:.3f}")
            except Exception as e:
                print(f"        ошибка: {e}")
            await asyncio.sleep(0.5)

    print("\nГотово — открой http://localhost:6006 и проверь трейсы.")


if __name__ == "__main__":
    asyncio.run(main())