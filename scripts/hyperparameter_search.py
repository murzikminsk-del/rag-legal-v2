"""
Подбор гиперпараметров: chunk_size, chunk_overlap, top_k.
Стратегия фиксирована: recursive (лучший результат с реранкером).
Без реранкера, чтобы не упираться в rate limit Cohere.

Запуск:
    python scripts/hyperparameter_search.py
"""
import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import get_settings
from app.services.chunking import chunk_text_async
from app.services.embeddings import embed_texts
from app.services.retrieval_eval import QAItem, _compute_metrics, _retrieve

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
BATCH_SIZE = 32
STRATEGY = "recursive"


@dataclass
class Experiment:
    name: str
    chunk_size: int
    chunk_overlap: int
    top_k: int


EXPERIMENTS = [
    Experiment("exp1_small",      chunk_size=256,  chunk_overlap=32,  top_k=5),
    Experiment("exp2_baseline",   chunk_size=512,  chunk_overlap=64,  top_k=5),
    Experiment("exp3_topk10",     chunk_size=256,  chunk_overlap=32,  top_k=10),
    Experiment("exp4_topk10_512", chunk_size=512,  chunk_overlap=64,  top_k=10),
    Experiment("exp5_topk20",     chunk_size=256,  chunk_overlap=32,  top_k=20),
    Experiment("exp6_topk20_512", chunk_size=512,  chunk_overlap=64,  top_k=20),
]

def _make_id(collection: str, source: str, idx: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{collection}:{source}:{idx}"))


async def index_experiment(
    client: QdrantClient,
    exp: Experiment,
    corpus_dir: Path,
    embedding_dim: int,
) -> None:
    col = f"hp_{exp.name}"
    existing = {c.name for c in client.get_collections().collections}
    if col in existing:
        client.delete_collection(col)
    client.create_collection(
        collection_name=col,
        vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
    )
    files = sorted(corpus_dir.glob("*.md"))
    all_points: list[PointStruct] = []
    for fpath in files:
        text = fpath.read_text(encoding="utf-8")
        chunks = await chunk_text_async(
            text=text,
            source=fpath.name,
            strategy=STRATEGY,
            chunk_size=exp.chunk_size,
            chunk_overlap=exp.chunk_overlap,
        )
        texts = [c.text for c in chunks]
        for i in range(0, len(texts), BATCH_SIZE):
            vecs = await embed_texts(texts[i : i + BATCH_SIZE])
            for chunk, vec in zip(chunks[i : i + BATCH_SIZE], vecs):
                all_points.append(
                    PointStruct(
                        id=_make_id(col, chunk.source, chunk.chunk_index),
                        vector=vec,
                        payload={"text": chunk.text, "source": chunk.source},
                    )
                )
    for i in range(0, len(all_points), BATCH_SIZE):
        client.upsert(collection_name=col, points=all_points[i : i + BATCH_SIZE])


async def eval_experiment(
    client: QdrantClient,
    exp: Experiment,
    dataset: list[QAItem],
) -> dict:
    col = f"hp_{exp.name}"
    retrieve_k = max(exp.top_k, 10)  # минимум 10 для MRR@10 и Recall@10
    retrieved: list[list[str]] = []
    relevant: list[set[str]] = []
    for item in dataset:
        points = await _retrieve(client, col, item["question"], top_k=retrieve_k)
        retrieved.append([p.payload.get("source", "") for p in points])
        relevant.append(set(item["relevant_doc_ids"]))
    return _compute_metrics(retrieved, relevant, k_hit=5, k_mrr=10, k_recall=10)

async def main() -> None:
    s = get_settings()
    client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, check_compatibility=False)
    dataset: list[QAItem] = json.loads(
        Path("tests/eval/retrieval_dataset.json").read_text(encoding="utf-8")
    )

    print(f"{'Эксперимент':<22} {'size':>5} {'ovlp':>5} {'k':>3} | {'HR@5':>7} {'MRR@10':>8} {'Rec@10':>8}")
    print("-" * 65)

    results = []
    for exp in EXPERIMENTS:
        print(f"  Индексирую {exp.name}...", end="", flush=True)
        await index_experiment(client, exp, s.rag_corpus_dir, s.embedding_dim)
        m = await eval_experiment(client, exp, dataset)
        print(
            f"\r{exp.name:<22} {exp.chunk_size:>5} {exp.chunk_overlap:>5} {exp.top_k:>3} | "
            f"{m['hit_rate']:>7.4f} {m['mrr']:>7.4f} {m['recall']:>7.4f}"
        )
        results.append((exp, m))

    # Лучший по MRR
    best_exp, best_m = max(results, key=lambda x: x[1]["mrr"])
    print(f"\nЛучший: {best_exp.name} — MRR={best_m['mrr']:.4f}")
    print(f"  chunk_size={best_exp.chunk_size}, chunk_overlap={best_exp.chunk_overlap}, top_k={best_exp.top_k}")

    # Обновляем docs/chunking_experiment.md
    md_path = Path("docs/chunking_experiment.md")
    content = md_path.read_text(encoding="utf-8")

    hp_section = (
        f"## Эксперименты по подбору гиперпараметров\n\n"
        f"Стратегия: `{STRATEGY}`. Метрики без реранкера.\n\n"
        f"| Эксперимент | chunk_size | chunk_overlap | top_k | Hit Rate | MRR | Recall |\n"
        f"|---|---|---|---|---|---|---|\n"
    )
    for exp, m in results:
        bold = "**" if exp == best_exp else ""
        hp_section += (
            f"| {bold}`{exp.name}`{bold} | {exp.chunk_size} | {exp.chunk_overlap} | "
            f"{exp.top_k} | {m['hit_rate']:.4f} | {m['mrr']:.4f} | {m['recall']:.4f} |\n"
        )

    bt = "```"
    hp_section += (
        f"\n**Лучшая конфигурация:** `{best_exp.name}`  \n"
        f"`chunk_size={best_exp.chunk_size}`, "
        f"`chunk_overlap={best_exp.chunk_overlap}`, "
        f"`top_k={best_exp.top_k}`\n\n"
        f"## Итоговая конфигурация\n\n"
        f"{bt}\n"
        f"chunk_size={best_exp.chunk_size}\n"
        f"chunk_overlap={best_exp.chunk_overlap}\n"
        f"similarity_top_k={best_exp.top_k}\n"
        f"chunking_strategy={STRATEGY}\n"
        f"{bt}\n"
    )

    updated = content.replace(
        "*(заполняется после шага 7)*\n\n## Итоговая конфигурация\n\n*(заполняется после шага 7)*",
        hp_section.strip(),
    )
    md_path.write_text(updated, encoding="utf-8")
    print("docs/chunking_experiment.md обновлён.")


if __name__ == "__main__":
    asyncio.run(main())