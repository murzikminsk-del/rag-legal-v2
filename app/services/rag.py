import os
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import get_settings

QA_PROMPT = (
    "Ты юридический ассистент. Отвечай ТОЛЬКО на основе предоставленного контекста. "
    "Если ответа в контексте нет — честно скажи: «В базе знаний нет ответа на этот вопрос.» "
    "Не выдумывай факты."
)


def _format_result(response) -> dict:
    nodes = response.source_nodes
    top_score = nodes[0].score if nodes else 0.0
    return {
        "answer": str(response),
        "top_score": round(top_score, 3),
        "sources": [
            {
                "text": n.text[:300],
                "source": n.metadata.get("file_name"),
                "score": round(n.score, 3),
            }
            for n in nodes
        ],
    }


class RAGService:
    def __init__(self):
        s = get_settings()
        self._collection = s.rag_collection
        self._corpus_dir = str(s.rag_corpus_dir)
        self._top_k = s.similarity_top_k
        self._threshold = s.rag_score_threshold

        Settings.embed_model = OpenAIEmbedding(
            model=s.embedding_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
            http_client=None,
        )
        Settings.llm = LlamaOpenAI(
            model=s.llm.default_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
            temperature=0.0,
            system_prompt=QA_PROMPT,
        )
        Settings.node_parser = SentenceSplitter(
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
        )

        self._client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            check_compatibility=False,
        )
        self._index: VectorStoreIndex | None = None

    def build(self) -> None:
        vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self._collection,
        )
        existing = {c.name for c in self._client.get_collections().collections}

        if self._collection in existing:
            self._index = VectorStoreIndex.from_vector_store(vector_store)
        else:
            storage = StorageContext.from_defaults(vector_store=vector_store)
            documents = SimpleDirectoryReader(
                input_dir=self._corpus_dir,
                recursive=True,
            ).load_data()
            self._index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage,
                show_progress=True,
            )

    def answer(self, question: str) -> dict:
        if self._index is None:
            raise RuntimeError("RAGService не инициализирован — вызови build() сначала")
        engine = self._index.as_query_engine(similarity_top_k=self._top_k)
        response = engine.query(question)
        result = _format_result(response)
        if result["top_score"] < self._threshold:
            result["answer"] = "В базе знаний нет ответа на этот вопрос."
        return result


_rag_service: RAGService | None = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


if __name__ == "__main__":
    import json
    svc = get_rag_service()
    svc.build()
    result = svc.answer("Какова неустойка за просрочку выполнения работ?")
    print(json.dumps(result, ensure_ascii=False, indent=2))