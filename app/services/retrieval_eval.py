"""
Оценка качества retrieval по golden датасету.

Метрики:
  Hit Rate@K  — хотя бы один релевантный документ в top-K
  MRR@K       — Mean Reciprocal Rank (1/rank первого попадания)
  Recall@K    — доля найденных релевантных из всех релевантных
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TypedDict

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint

from app.core.config import get_settings
from app.services.embeddings import embed_texts


class QAItem(TypedDict):
    question: str
    relevant_doc_ids: list[str]


class MetricsResult(TypedDict):
    collection: str
    hit_rate_at_k: float
    mrr_at_k: float
    recall_at_k: float
    k: int
    n_questions: int


async def _retrieve(
    client: QdrantClient,
    collection: str,
    question: str,
    top_k: int,
) -> list[ScoredPoint]:
    vectors = await embed_texts([question])
    results = client.query_points(
        collection_name=collection,
        query=vectors[0],
        limit=top_k,
        with_payload=True,
    )
    return results.points


def _compute_metrics(
    retrieved_sources: list[list[str]],
    relevant_sets: list[set[str]],
    k_hit: int = 5,
    k_mrr: int = 10,
    k_recall: int = 10,
) -> dict[str, float]:
    hit_rates, reciprocal_ranks, recalls = [], [], []

    for sources, relevant in zip(retrieved_sources, relevant_sets):
        # Hit Rate@5
        top_hit = sources[:k_hit]
        hit = any(s in relevant for s in top_hit)
        hit_rates.append(1.0 if hit else 0.0)

        # MRR@10
        top_mrr = sources[:k_mrr]
        rr = 0.0
        for rank, s in enumerate(top_mrr, start=1):
            if s in relevant:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        # Recall@10
        top_recall = sources[:k_recall]
        found_docs = {s for s in top_recall if s in relevant}
        recalls.append(len(found_docs) / len(relevant) if relevant else 0.0)

    return {
        "hit_rate": sum(hit_rates) / len(hit_rates),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "recall": sum(recalls) / len(recalls),
    }


async def evaluate_collection(
    client: QdrantClient,
    collection: str,
    dataset: list[QAItem],
    k_hit: int = 5,
    k_mrr: int = 10,
    k_recall: int = 10,
) -> MetricsResult:
    retrieve_k = max(k_hit, k_mrr, k_recall)
    retrieved_sources: list[list[str]] = []
    relevant_sets: list[set[str]] = []

    for item in dataset:
        points = await _retrieve(client, collection, item["question"], top_k=retrieve_k)
        sources = [p.payload.get("source", "") for p in points]
        retrieved_sources.append(sources)
        relevant_sets.append(set(item["relevant_doc_ids"]))

    m = _compute_metrics(retrieved_sources, relevant_sets, k_hit, k_mrr, k_recall)
    return MetricsResult(
        collection=collection,
        hit_rate_at_k=round(m["hit_rate"], 4),
        mrr_at_k=round(m["mrr"], 4),
        recall_at_k=round(m["recall"], 4),
        k=retrieve_k,
        n_questions=len(dataset),
    )


async def run_evaluation(
    dataset_path: str = "tests/eval/retrieval_dataset.json",
    collections: list[str] | None = None,
    k_hit: int = 5,
    k_mrr: int = 10,
    k_recall: int = 10,
) -> list[MetricsResult]:
    s = get_settings()
    client = QdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        check_compatibility=False,
    )
    dataset: list[QAItem] = json.loads(Path(dataset_path).read_text(encoding="utf-8"))

    if collections is None:
        collections = ["docs_fixed", "docs_recursive", "docs_semantic"]

    results = []
    for col in collections:
        print(f"Оцениваю {col} (HR@{k_hit}, MRR@{k_mrr}, Recall@{k_recall})...")
        result = await evaluate_collection(client, col, dataset, k_hit, k_mrr, k_recall)
        results.append(result)
        print(
            f"  Hit Rate@{k_hit}: {result['hit_rate_at_k']:.4f} | "
            f"MRR@{k_mrr}: {result['mrr_at_k']:.4f} | "
            f"Recall@{k_recall}: {result['recall_at_k']:.4f}"
        )
    return results


if __name__ == "__main__":
    asyncio.run(run_evaluation())