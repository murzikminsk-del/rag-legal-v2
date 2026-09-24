"""
Сравнивает метрики retrieval до и после Cohere Rerank.
Результаты выводит в консоль и добавляет в docs/chunking_experiment.md.

Запуск:
    python scripts/eval_with_reranker.py
"""
import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from app.core.config import get_settings
from app.services.retrieval_eval import QAItem, _compute_metrics, _retrieve
from app.services.reranker import rerank
from qdrant_client import QdrantClient

COLLECTIONS = ["docs_fixed", "docs_recursive", "docs_semantic"]
RETRIEVE_K = 10   # берём top-10 для реранкера
FINAL_K = 5       # после реранка оцениваем top-5


async def evaluate_with_reranker(
    client: QdrantClient,
    collection: str,
    dataset: list[QAItem],
    retrieve_k: int,
    final_k: int,
) -> dict:
    before_sources: list[list[str]] = []
    after_sources: list[list[str]] = []
    relevant_sets: list[set[str]] = []
    

    for item in dataset:
        # 1. Ретривал top-retrieve_k
        points = await _retrieve(client, collection, item["question"], top_k=retrieve_k)
        texts = [p.payload.get("text", "") for p in points]
        sources = [p.payload.get("source", "") for p in points]

        before_sources.append(sources[:final_k])

        # 2. Реранк
        ranked = rerank(
            question=item["question"],
            texts=texts,
            sources=sources,
            top_n=final_k,
        )
        after_sources.append([r.source for r in ranked])
        relevant_sets.append(set(item["relevant_doc_ids"]))
        await asyncio.sleep(6)  # trial key: 10 req/min

    before = _compute_metrics(before_sources, relevant_sets, k_hit=final_k, k_mrr=final_k, k_recall=final_k)
    after = _compute_metrics(after_sources, relevant_sets, k_hit=final_k, k_mrr=final_k, k_recall=final_k)
    return {"before": before, "after": after}


async def main() -> None:
    s = get_settings()
    client = QdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        check_compatibility=False,
    )
    dataset: list[QAItem] = json.loads(
        Path("tests/eval/retrieval_dataset.json").read_text(encoding="utf-8")
    )

    print(f"\nРетривал top-{RETRIEVE_K}, оцениваем top-{FINAL_K} до/после Cohere Rerank\n")
    print(f"{'Коллекция':<20} {'До MRR':>8} {'До HR':>8} | {'После MRR':>10} {'После HR':>9}")
    print("-" * 65)

    table_rows = []
    for col in COLLECTIONS:
        print(f"  {col}...", end="", flush=True)
        res = await evaluate_with_reranker(client, col, dataset, RETRIEVE_K, FINAL_K)
        b, a = res["before"], res["after"]
        print(
            f"\r{col:<20} "
            f"{b['hit_rate']:>8.4f} {b['mrr']:>8.4f} | "
            f"{a['hit_rate']:>10.4f} {a['mrr']:>9.4f}"
        )
        table_rows.append((col, b, a))

    # Обновляем docs/chunking_experiment.md
    md_path = Path("docs/chunking_experiment.md")
    content = md_path.read_text(encoding="utf-8")

    reranker_section = f"""## Результаты с Cohere Rerank

Стратегия: ретривал top-{RETRIEVE_K}, реранк Cohere `rerank-v3.5`, оценка top-{FINAL_K}.

| Коллекция | Hit Rate до | MRR до | Hit Rate после | MRR после | Delta MRR |
|---|---|---|---|---|---|
"""
    for col, b, a in table_rows:
        delta = a["mrr"] - b["mrr"]
        sign = "+" if delta >= 0 else ""
        reranker_section += (
            f"| `{col}` | {b['hit_rate']:.4f} | {b['mrr']:.4f} | "
            f"{a['hit_rate']:.4f} | {a['mrr']:.4f} | {sign}{delta:.4f} |\n"
        )

    best = max(table_rows, key=lambda x: x[2]["mrr"])
    reranker_section += (
        f"\n**Лучший результат после реранка:** `{best[0]}` — MRR@{FINAL_K}: {best[2]['mrr']:.4f}\n"
    )

    # Заменяем placeholder
    updated = content.replace(
        "*(заполняется после шага 6)*",
        reranker_section.strip(),
    )
    md_path.write_text(updated, encoding="utf-8")
    print(f"\ndocs/chunking_experiment.md обновлён.")


if __name__ == "__main__":
    asyncio.run(main())