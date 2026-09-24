"""Проверочный набор: поиск (top-N) и ответы бота по eval/qa_set.json.

Две проверки на каждый вопрос:
- поиск — попал ли нужный фрагмент документа в то, что уходит модели;
- ответ — вопрос задаётся настоящему боту через бэкенд (как из Telegram),
  в ответе ищутся правильные цифры/слова (must_contain) и запрещённые (must_not_contain).

Запуск из корня проекта (бэкенд запущен, прокси включён — . .\\proxy.ps1):
    uv run python eval/run_qa.py
    uv run python eval/run_qa.py --only-search     # только поиск, без вызова бота
Результат: таблица в консоли и eval/runs/qa_<дата_время>.json для сравнения «до/после».
"""

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")

from app.services.rag import RAGService  # noqa: E402

APP_URL = "http://localhost:8000"


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е").replace("\xa0", " ")


def check_answer(answer: str, item: dict) -> bool:
    """Все группы must_contain найдены (в группе — любой вариант) и нет must_not_contain."""
    a = _norm(answer)
    has_all = all(any(_norm(v) in a for v in group) for group in item["must_contain"])
    has_forbidden = any(_norm(v) in a for v in item.get("must_not_contain", []))
    return has_all and not has_forbidden


def check_search(rag: RAGService, item: dict) -> bool | None:
    """Нужный фрагмент среди того, что уходит модели. None — для вопроса нет эталона."""
    if "doc" not in item:
        return None
    return any(
        f"{n.metadata.get('category')}/{n.metadata.get('source')}" == item["doc"]
        and _norm(item["needle"]) in _norm(n.text)
        for n in rag._retrieve_nodes(item["question"])
    )


def ask_chat(http: httpx.Client, question: str) -> str:
    """Вопрос в новом чате (без истории), как обычное сообщение боту."""
    chat_id = http.post("/chats", json={"owner_external_id": "eval", "interface": "eval"}).json()["chat_id"]
    tokens: list[str] = []
    with http.stream("POST", f"/chats/{chat_id}/messages", data={"content": question}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line.removeprefix("data: "))
                if event["type"] == "token":
                    tokens.append(event["delta"])
    http.delete(f"/chats/{chat_id}/messages")
    return "".join(tokens)


def ask_agent(http: httpx.Client, question: str, thread_id: str) -> str:
    """Вопрос агенту (/agent) в отдельном потоке, после ответа история стирается."""
    r = http.post("/agent/chat", json={"message": question, "thread_id": thread_id})
    r.raise_for_status()
    http.delete(f"/agent/threads/{thread_id}")
    return r.json().get("answer") or ""


def _mark(ok: bool | None) -> str:
    return {True: "✓", False: "✗", None: "—"}[ok]


def _score(results: list[dict], key: str) -> str:
    checked = [r[key] for r in results if r[key] is not None]
    return f"{sum(checked)}/{len(checked)}" if checked else "—"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qa", default="eval/qa_set.json")
    ap.add_argument("--out-dir", default="eval/runs")
    ap.add_argument("--only-search", action="store_true", help="не задавать вопросы боту")
    args = ap.parse_args()

    items = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    rag = RAGService()
    rag.build()
    http = httpx.Client(base_url=APP_URL, timeout=180, trust_env=False)

    results = []
    for item in items:
        search_ok = check_search(rag, item)
        answer, answer_ok = None, None
        if not args.only_search:
            if item["mode"] == "agent":
                answer = ask_agent(http, item["question"], f"eval-{item['id']}")
            else:
                answer = ask_chat(http, item["question"])
            answer_ok = check_answer(answer, item)
        results.append({**item, "search_ok": search_ok, "answer_ok": answer_ok, "answer": answer})
        print(f"{item['id']:>3}  поиск {_mark(search_ok)}  ответ {_mark(answer_ok)}  {item['question']}")

    summary = {"search": _score(results, "search_ok"), "answer": _score(results, "answer_ok")}
    print(f"\nПоиск: нужный фрагмент в контексте — {summary['search']}")
    print(f"Ответы: правильных — {summary['answer']}")

    for r in results:
        if r["answer_ok"] is False:
            print(f"\n✗ {r['id']}. {r['question']}\n  ответ: {r['answer'][:300]}")

    out = Path(args.out_dir) / f"qa_{datetime.now():%Y-%m-%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"timestamp": datetime.now().isoformat(timespec="seconds"), "summary": summary,
                    "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()
