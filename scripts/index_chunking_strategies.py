"""
Индексирует корпус data/rag-block-03/ тремя стратегиями чанкинга
в коллекции Qdrant: docs_fixed, docs_recursive, docs_semantic.

Запуск:
    python scripts/index_chunking_strategies.py
"""
import asyncio
import os
import uuid
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import get_settings
from app.services.chunking import Strategy, chunk_text_async
from app.services.embeddings import embed_texts

STRATEGIES: list[Strategy] = ["fixed_size", "recursive", "semantic"]
COLLECTION_MAP = {
    "fixed_size": "docs_fixed",
    "recursive": "docs_recursive",
    "semantic": "docs_semantic",
}

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
BATCH_SIZE = 32


def _make_id(collection: str, source: str, idx: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{collection}:{source}:{idx}"))


async def index_strategy(
    client: QdrantClient,
    strategy: Strategy,
    corpus_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    embedding_dim: int,
) -> None:
    collection = COLLECTION_MAP[strategy]
    print(f"\n=== Стратегия: {strategy} → коллекция: {collection} ===")

    # пересоздаём коллекцию
    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        client.delete_collection(collection)
        print(f"  Удалена старая коллекция {collection}")
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
    )

    # читаем файлы
    files = sorted(corpus_dir.glob("*.md"))
    print(f"  Файлов: {len(files)}")

    all_points: list[PointStruct] = []
    for fpath in files:
        text = fpath.read_text(encoding="utf-8")
        chunks = await chunk_text_async(
            text=text,
            source=fpath.name,
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        print(f"  {fpath.name}: {len(chunks)} чанков")

        # эмбеддируем батчами
        texts = [c.text for c in chunks]
        for i in range(0, len(texts), BATCH_SIZE):
            batch_texts = texts[i : i + BATCH_SIZE]
            batch_chunks = chunks[i : i + BATCH_SIZE]
            vectors = await embed_texts(batch_texts)
            for chunk, vec in zip(batch_chunks, vectors):
                all_points.append(
                    PointStruct(
                        id=_make_id(collection, chunk.source, chunk.chunk_index),
                        vector=vec,
                        payload={
                            "text": chunk.text,
                            "source": chunk.source,
                            "chunk_index": chunk.chunk_index,
                            "strategy": strategy,
                        },
                    )
                )

    # заливаем в Qdrant батчами
    total = len(all_points)
    print(f"  Всего точек: {total}. Загружаем в Qdrant...")
    for i in range(0, total, BATCH_SIZE):
        batch = all_points[i : i + BATCH_SIZE]
        client.upsert(collection_name=collection, points=batch)
        print(f"  Загружено {min(i + BATCH_SIZE, total)}/{total}", end="\r")
    print(f"\n  Готово: {collection}")


async def main() -> None:
    s = get_settings()
    client = QdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        check_compatibility=False,
    )
    for strategy in STRATEGIES:
        await index_strategy(
            client=client,
            strategy=strategy,
            corpus_dir=s.rag_corpus_dir,
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            embedding_dim=s.embedding_dim,
        )
    print("\n✓ Все три коллекции проиндексированы.")


if __name__ == "__main__":
    asyncio.run(main())