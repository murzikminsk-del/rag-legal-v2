import os
import pytest

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("LLM__OPENAI_API_KEY", "sk-test-fake")

from app.services.vector_store import VectorStore
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "dev-secret-key")
TEST_COLLECTION = "test_smoke"
DIM = 4


@pytest.fixture
async def store():
    vs = VectorStore(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        collection=TEST_COLLECTION,
        dim=DIM,
    )
    await vs.ensure_collection()
    yield vs
    await vs.client.delete_collection(TEST_COLLECTION)
    await vs.close()


async def test_ensure_collection_creates(store: VectorStore):
    collections = await store.client.get_collections()
    names = {c.name for c in collections.collections}
    assert TEST_COLLECTION in names


async def test_upsert_and_search(store: VectorStore):
    points = [
        PointStruct(id="11111111-1111-1111-1111-111111111111", vector=[1.0, 0.0, 0.0, 0.0], payload={"text": "договор аренды", "source": "a.md", "category": "contract", "created_at": "2024-01-01T00:00:00Z"}),
        PointStruct(id="22222222-2222-2222-2222-222222222222", vector=[0.0, 1.0, 0.0, 0.0], payload={"text": "политика данных", "source": "b.md", "category": "policy", "created_at": "2025-01-01T00:00:00Z"}),
        PointStruct(id="33333333-3333-3333-3333-333333333333", vector=[0.0, 0.0, 1.0, 0.0], payload={"text": "NDA соглашение", "source": "c.md", "category": "nda", "created_at": "2025-06-01T00:00:00Z"}),
    ]
    await store.upsert(points)

    results = await store.search(query_vector=[1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert str(results[0].id) == "11111111-1111-1111-1111-111111111111"


async def test_search_with_filter(store: VectorStore):
    points = [
        PointStruct(id="44444444-4444-4444-4444-444444444444", vector=[1.0, 0.0, 0.0, 0.0], payload={"text": "договор подряда", "source": "d.md", "category": "contract", "created_at": "2024-03-01T00:00:00Z"}),
        PointStruct(id="55555555-5555-5555-5555-555555555555", vector=[0.9, 0.1, 0.0, 0.0], payload={"text": "агентский договор", "source": "e.md", "category": "nda", "created_at": "2024-05-01T00:00:00Z"}),
    ]
    await store.upsert(points)

    f = Filter(must=[FieldCondition(key="category", match=MatchValue(value="contract"))])
    results = await store.search(query_vector=[1.0, 0.0, 0.0, 0.0], top_k=5, query_filter=f)
    categories = {r.payload["category"] for r in results}
    assert categories == {"contract"}