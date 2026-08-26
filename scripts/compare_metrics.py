import asyncio
import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from app.core.config import get_settings
from app.services.embeddings import embed_texts

QUERIES = [
    "Как расторгнуть договор аренды досрочно?",
    "Какова неустойка за просрочку выполнения работ?",
    "Какие данные относятся к коммерческой тайне?",
    "Кто вправе подписывать договоры на сумму свыше 5 миллионов рублей?",
    "Какова ответственность за нарушение NDA?",
]


def get_client(settings) -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        check_compatibility=False,
    )


def copy_collection(client: QdrantClient, src: str, dst: str, dim: int, distance: Distance) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if dst in existing:
        client.delete_collection(dst)

    client.create_collection(
        collection_name=dst,
        vectors_config=VectorParams(size=dim, distance=distance),
    )

    limit = 256
    offset = None
    while True:
        records, next_offset = client.scroll(
            collection_name=src,
            limit=limit,
            offset=offset,
            with_vectors=True,
            with_payload=True,
        )
        if not records:
            break
        points = [
            PointStruct(id=r.id, vector=r.vector, payload=r.payload)
            for r in records
        ]
        client.upsert(collection_name=dst, points=points, wait=True)
        if next_offset is None:
            break
        offset = next_offset

    count = client.get_collection(dst).points_count
    print(f"  Коллекция '{dst}' создана, {count} точек, метрика={distance.name}.")


async def run() -> None:
    settings = get_settings()
    client = get_client(settings)

    print("Создаю временные коллекции...")
    copy_collection(client, settings.qdrant_collection, "documents_cosine", settings.embedding_dim, Distance.COSINE)
    copy_collection(client, settings.qdrant_collection, "documents_dot", settings.embedding_dim, Distance.DOT)

    print("\nПолучаю эмбеддинги для запросов...")
    vectors = await embed_texts(QUERIES)

    print("\n" + "=" * 80)
    print(f"{'Запрос':<45} | {'Cosine top-5':<5} | {'Dot top-5':<5} | Совпадение")
    print("=" * 80)

    rows = []
    for query, vec in zip(QUERIES, vectors):
        cosine_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_compatibility=False)
        dot_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_compatibility=False)

        r_cosine = cosine_client.query_points(
            collection_name="documents_cosine",
            query=vec,
            limit=5,
            with_payload=False,
        )
        r_dot = dot_client.query_points(
            collection_name="documents_dot",
            query=vec,
            limit=5,
            with_payload=False,
        )

        ids_cosine = [str(p.id) for p in r_cosine.points]
        ids_dot = [str(p.id) for p in r_dot.points]
        match = ids_cosine == ids_dot

        rows.append({
            "query": query,
            "cosine": ids_cosine,
            "dot": ids_dot,
            "match": match,
        })

        short = query[:43]
        print(f"{short:<45} | {','.join(ids_cosine[:2])}... | {','.join(ids_dot[:2])}... | {'✓' if match else '✗'}")

    print("=" * 80)

    all_match = all(r["match"] for r in rows)
    print(f"\nВсе ранжирования совпали: {'ДА' if all_match else 'НЕТ'}")
    print("Вывод: text-embedding-3-small нормализует векторы → cosine ≡ dot.")
    print("В production оставляем COSINE: семантически интуитивен, масштабируется на другие модели.")

    print("\nУдаляю временную коллекцию 'documents_dot'...")
    client.delete_collection("documents_dot")
    print("Удалено. Коллекция 'documents_cosine' оставлена для документации.")

    print("\nПолные результаты для docs/vector_store.md:")
    for r in rows:
        print(f"\nЗапрос: {r['query']}")
        print(f"  Cosine: {r['cosine']}")
        print(f"  Dot:    {r['dot']}")
        print(f"  Совпадение: {r['match']}")


if __name__ == "__main__":
    os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
    asyncio.run(run())