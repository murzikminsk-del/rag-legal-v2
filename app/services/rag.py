import os
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

import logging

from llama_index.core import Settings, VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import get_settings

log = logging.getLogger(__name__)

COLLECTION = "rag_legal_v2"
FINAL_TOP_N = 5  # сколько фрагментов уходит в LLM после реранка
NOT_FOUND = "По базе не нашёл, могу эскалировать."

SYSTEM_PROMPT = (
    "Ты юридический ассистент. Отвечай ТОЛЬКО на основе предоставленного контекста. "
    f"Если ответа в контексте нет — пиши: «{NOT_FOUND}» "
    "Не выдумывай факты."
)

CITATION_INSTRUCTION = (
    "Ответь на вопрос, ссылаясь на источники в формате [1], [2] и т.д. "
    "Используй только факты из приведённого контекста."
)


def _format_context(nodes: list) -> str:
    """Пронумерованный контекст для LLM: [N] и текст чанка (шапка «договор · файл · раздел» уже в нём)."""
    return "\n\n---\n\n".join(f"[{i}] {node.text}" for i, node in enumerate(nodes, start=1))


def _top_score(nodes: list) -> float:
    """Лучшая косинусная близость среди найденных фрагментов (0.0, если пусто)."""
    return max((n.score or 0.0 for n in nodes), default=0.0)


def _build_prompt(question: str, nodes: list, chat_history: list[dict] | None = None) -> str:
    history_text = ""
    if chat_history:
        lines = []
        for msg in chat_history[-6:]:
            role = "Пользователь" if msg.get("role") == "user" else "Ассистент"
            lines.append(f"{role}: {msg.get('content', '')}")
        history_text = "История диалога:\n" + "\n".join(lines) + "\n\n"

    return (
        f"{history_text}"
        f"Контекст:\n\n{_format_context(nodes)}\n\n"
        f"Вопрос: {question}\n\n"
        f"{CITATION_INSTRUCTION}"
    )


def _format_sources(nodes) -> list[dict]:
    sources = []
    for i, n in enumerate(nodes, start=1):
        meta = n.metadata or {}
        sources.append({
            "id": i,
            "file_name": meta.get("source") or meta.get("file_name") or "",
            "category": meta.get("category", ""),
            "page": meta.get("page_label") or meta.get("page"),
            "score": round(n.score, 4) if n.score is not None else 0.0,
            "snippet": n.text[:300].replace("\n", " "),
        })
    return sources


class RAGService:
    def __init__(self):
        s = get_settings()
        self._top_k = s.similarity_top_k
        self._threshold = s.rag_score_threshold

        Settings.embed_model = OpenAIEmbedding(
            model=s.embedding_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
        )
        Settings.llm = LlamaOpenAI(
            model=s.llm.default_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
            temperature=0.0,
            system_prompt=SYSTEM_PROMPT,
        )

        self._client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            check_compatibility=False,
        )
        self._index: VectorStoreIndex | None = None
        self._use_reranker: bool = bool(s.cohere_api_key)

    def build(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION not in existing:
            raise RuntimeError(
                f"Коллекция {COLLECTION!r} не найдена. "
                "Сначала запустите: python scripts/ingest.py data/"
            )
        vector_store = QdrantVectorStore(client=self._client, collection_name=COLLECTION)
        self._index = VectorStoreIndex.from_vector_store(vector_store)

    def _require_index(self) -> VectorStoreIndex:
        if self._index is None:
            raise RuntimeError("RAGService не инициализирован — вызови build() сначала")
        return self._index

    def _retrieve_nodes(self, query: str) -> list:
        """Векторный поиск top_k → реранк Cohere (если есть ключ) → FINAL_TOP_N лучших.

        node.score остаётся косинусной близостью из Qdrant, поэтому порог
        rag_score_threshold всегда сравнивается с одной и той же шкалой.
        """
        retriever = self._require_index().as_retriever(similarity_top_k=self._top_k)
        nodes = retriever.retrieve(query)
        if self._use_reranker and nodes:
            try:
                from app.services.reranker import rerank
                ranked = rerank(
                    query,
                    [n.text for n in nodes],
                    [n.metadata.get("source", "") for n in nodes],
                    top_n=FINAL_TOP_N,
                )
                return [nodes[r.original_index] for r in ranked]
            except Exception:
                log.exception("rerank_failed")
        return nodes[:FINAL_TOP_N]

    def _condense(self, question: str, chat_history: list[dict]) -> str:
        if len(question.split()) > 6:
            return question
        lines = [f"{m.get('role', '')}: {m.get('content', '')}" for m in chat_history[-4:]]
        prompt = (
            "История:\n" + "\n".join(lines) +
            f"\n\nТекущий вопрос: {question}\n\n"
            "Перепиши вопрос как самодостаточный (без ссылок на историю). "
            "Только вопрос, без пояснений."
        )
        return str(Settings.llm.complete(prompt)).strip()

    def retrieve_context(self, question: str, chat_history: list[dict] | None = None) -> str:
        """Только retrieval без LLM: возвращает пронумерованный контекст или ''."""
        if self._index is None:
            return ""
        query = self._condense(question, chat_history) if chat_history else question
        nodes = self._retrieve_nodes(query)
        if _top_score(nodes) < self._threshold:
            return ""
        return _format_context(nodes)

    def answer(self, question: str, chat_history: list[dict] | None = None) -> dict:
        query = self._condense(question, chat_history) if chat_history else question
        nodes = self._retrieve_nodes(query)
        top_score = _top_score(nodes)
        confident = top_score >= self._threshold

        if confident:
            answer_text = str(Settings.llm.complete(_build_prompt(question, nodes, chat_history)))
        else:
            answer_text = NOT_FOUND

        return {
            "answer": answer_text,
            "top_score": round(top_score, 4),
            "confident": confident,
            "sources": _format_sources(nodes),
        }

    def evaluate_inputs(self, question: str) -> dict:
        """Для eval-пайплайна: возвращает answer + полный список retrieved_contexts."""
        nodes = self._retrieve_nodes(question)
        if _top_score(nodes) < self._threshold:
            answer_text = NOT_FOUND
        else:
            answer_text = str(Settings.llm.complete(_build_prompt(question, nodes)))
        return {
            "answer": answer_text,
            "retrieved_contexts": [n.text for n in nodes],
        }


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
    # Тест мультитёрн
    q1 = "Какой штраф за просрочку ввода объекта в эксплуатацию по Ростовскому соглашению?"
    r1 = svc.answer(q1)
    print("Вопрос 1:", json.dumps(r1["answer"], ensure_ascii=False))
    r2 = svc.answer("а по Вологодскому?", chat_history=[
        {"role": "user", "content": q1},
        {"role": "assistant", "content": r1["answer"]},
    ])
    print("Вопрос 2 (follow-up):", json.dumps(r2["answer"], ensure_ascii=False))