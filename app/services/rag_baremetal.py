import os
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

import asyncio
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams, PayloadSchemaType

from app.core.config import get_settings
from app.services.embeddings import embed_texts

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

SYSTEM_PROMPT = (
    "Ты юридический ассистент. Отвечай ТОЛЬКО на основе предоставленного контекста. "
    "Если ответа в контексте нет — честно скажи: «В базе знаний нет ответа на этот вопрос.» "
    "Не выдумывай факты."
)


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks = []
    step = chunk_size - chunk_overlap
    for i in range(0, len(text), step):
        chunk = text[i : i + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def _make_id(source: str, idx: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{source}:{idx}"))


class BareMetalRAG:
    def __init__(self):
        s = get_settings()
        self._collection = s.rag_baremetal_collection
        self._corpus_dir = Path(s.rag_corpus_dir)
        self._chunk_size = s.chunk_size
        self._chunk_overlap = s.chunk_overlap
        self._top_k = s.similarity_top_k
        self._threshold = s.rag_score_threshold
        self._dim = s.embedding_dim
        self._settings = s

        self._client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            check_compatibility=False,
        )

    def ensure_indexed(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )
        self._client.create_payload_index(
            self._collection, "source", PayloadSchemaType.KEYWORD
        )

        files = list(self._corpus_dir.rglob("*.md")) + list(self._corpus_dir.rglob("*.txt"))
        all_chunks: list[str] = []
        all_sources: list[str] = []

        for path in files:
            text = path.read_text(encoding="utf-8")
            chunks = _chunk_text(text, self._chunk_size, self._chunk_overlap)
            all_chunks.extend(chunks)
            all_sources.extend([path.name] * len(chunks))

        vectors = asyncio.run(embed_texts(all_chunks))

        points = [
            PointStruct(
                id=_make_id(all_sources[i], i),
                vector=vectors[i],
                payload={"text": all_chunks[i], "source": all_sources[i]},
            )
            for i in range(len(all_chunks))
        ]

        batch_size = 64
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=self._collection,
                points=points[i : i + batch_size],
                wait=(i + batch_size >= len(points)),
            )

    def answer(self, question: str) -> dict:
        import openai as _openai

        q_vec = asyncio.run(embed_texts([question]))[0]

        hits = self._client.query_points(
            collection_name=self._collection,
            query=q_vec,
            limit=self._top_k,
            with_payload=True,
        ).points

        top_score = hits[0].score if hits else 0.0

        if top_score < self._threshold:
            return {
                "answer": "В базе знаний нет ответа на этот вопрос.",
                "top_score": round(top_score, 3),
                "sources": [],
            }

        context = "\n\n".join(
            f"[{h.payload['source']}]\n{h.payload['text']}" for h in hits
        )

        client = _openai.OpenAI(
            api_key=self._settings.llm.openai_api_key.get_secret_value(),
        )
        resp = client.chat.completions.create(
            model=self._settings.llm.default_model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Контекст:\n{context}\n\nВопрос: {question}"},
            ],
        )
        answer = resp.choices[0].message.content

        return {
            "answer": answer,
            "top_score": round(top_score, 3),
            "sources": [
                {
                    "text": h.payload["text"][:300],
                    "source": h.payload["source"],
                    "score": round(h.score, 3),
                }
                for h in hits
            ],
        }


if __name__ == "__main__":
    import json
    rag = BareMetalRAG()
    rag.ensure_indexed()
    result = rag.answer("Какова неустойка за просрочку выполнения работ?")
    print(json.dumps(result, ensure_ascii=False, indent=2))