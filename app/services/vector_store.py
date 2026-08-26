

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    HnswConfigDiff,
    PayloadSchemaType,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.core.config import get_settings


class VectorStore:
    def __init__(self, url: str, api_key: str | None, collection: str, dim: int) -> None:
        self.client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
            check_compatibility=False,
        )
        self.collection = collection
        self.dim = dim

    async def ensure_collection(self) -> None:
        existing = {c.name for c in (await self.client.get_collections()).collections}

        if self.collection in existing:
            info = await self.client.get_collection(self.collection)
            actual_dim = info.config.params.vectors.size
            if actual_dim != self.dim:
                raise ValueError(
                    f"Коллекция '{self.collection}' существует с размерностью "
                    f"{actual_dim}, ожидалось {self.dim}."
                )
            return

        # Оставляем default Qdrant HNSW: m=16, ef_construct=100 —
        # для датасетов до ~1M векторов это оптимальный баланс recall и скорости.
        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(
                size=self.dim,
                distance=Distance.COSINE,
            ),
        )
        await self.client.create_payload_index(self.collection, "source", PayloadSchemaType.KEYWORD)
        await self.client.create_payload_index(self.collection, "created_at", PayloadSchemaType.DATETIME)
        await self.client.create_payload_index(self.collection, "category", PayloadSchemaType.KEYWORD)

    async def upsert(self, points: list[PointStruct], batch_size: int = 256) -> None:
        for i in range(0, len(points), batch_size):
            await self.client.upsert(
                collection_name=self.collection,
                points=points[i : i + batch_size],
                wait=(i + batch_size >= len(points)),
            )

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        query_filter: Filter | None = None,
    ) -> list[ScoredPoint]:
        result = await self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return result.points

    async def close(self) -> None:
        await self.client.close()


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        settings = get_settings()
        _vector_store = VectorStore(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
            dim=settings.embedding_dim,
        )
    return _vector_store