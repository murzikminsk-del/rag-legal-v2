import asyncio
import json
import uuid

from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
    HnswConfigDiff,
)
from tqdm import tqdm

from app.core.config import get_settings
from app.services.embeddings import embed_texts

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL
DATA_FILE = Path("data/documents.json")
BATCH_SIZE = 128


def make_id(chunk_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, chunk_id))


def get_client(settings) -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        check_compatibility=False,
    )

def ensure_collection(client: QdrantClient, settings) -> None:
    existing = {c.name for c in client.get_collections().collections}

    if settings.qdrant_collection in existing:
        info = client.get_collection(settings.qdrant_collection)
        actual_dim = info.config.params.vectors.size
        if actual_dim != settings.embedding_dim:
            raise ValueError(
                f"Коллекция '{settings.qdrant_collection}' существует с размерностью "
                f"{actual_dim}, но settings.EMBEDDING_DIM={settings.embedding_dim}. "
                f"Удали коллекцию вручную или исправь конфиг."
            )
        print(f"Коллекция '{settings.qdrant_collection}' уже существует, размерность совпадает ({actual_dim}). Пропускаю создание.")
        return

    # Оставляем default Qdrant HNSW: m=16, ef_construct=100 —
    # для 100–10k векторов это оптимальный баланс точности и скорости индексации.
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=VectorParams(
            size=settings.embedding_dim,
            distance=Distance.COSINE,
        ),
    )
    print(f"Коллекция '{settings.qdrant_collection}' создана (dim={settings.embedding_dim}, COSINE).")

    client.create_payload_index(settings.qdrant_collection, "source", PayloadSchemaType.KEYWORD)
    client.create_payload_index(settings.qdrant_collection, "created_at", PayloadSchemaType.DATETIME)
    client.create_payload_index(settings.qdrant_collection, "category", PayloadSchemaType.KEYWORD)
    print("Payload-индексы созданы: source, created_at, category.")


async def load() -> None:
    settings = get_settings()
    client = get_client(settings)

    ensure_collection(client, settings)

    chunks = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    print(f"Загружено {len(chunks)} чанков из {DATA_FILE}.")

    texts = [c["text"] for c in chunks]
    print("Получаю эмбеддинги...")
    vectors = await embed_texts(texts)

    points = [
        PointStruct(
            id=make_id(c["id"]),
            vector=vectors[i],
            payload={
                "source": c["source"],
                "text": c["text"],
                "created_at": c["created_at"],
                "category": c["category"],
                "chunk_id": c["id"],
            },
        )
        for i, c in enumerate(chunks)
    ]

    total = len(points)
    for start in tqdm(range(0, total, BATCH_SIZE), desc="Upsert батчи"):
        batch = points[start : start + BATCH_SIZE]
        is_last = (start + BATCH_SIZE) >= total
        client.upsert(
            collection_name=settings.qdrant_collection,
            points=batch,
            wait=is_last,
        )

    count = client.get_collection(settings.qdrant_collection).points_count
    print(f"\nГотово! Точек в коллекции '{settings.qdrant_collection}': {count}")


if __name__ == "__main__":
    import os
    os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
    asyncio.run(load())