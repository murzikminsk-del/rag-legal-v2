import os
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import get_settings

COLLECTION = "rag_legal_v2"

SYSTEM_PROMPT = (
    "Ты юридический ассистент. Отвечай ТОЛЬКО на основе предоставленного контекста. "
    "Если ответа в контексте нет — пиши: «По базе не нашёл, могу эскалировать.» "
    "Не выдумывай факты."
)

CITATION_INSTRUCTION = (
    "Ответь на вопрос, ссылаясь на источники в формате [1], [2] и т.д. "
    "Используй только факты из приведённого контекста."
)


def _build_prompt(question: str, nodes: list, chat_history: list[dict] | None = None) -> str:
    parts = []
    for i, node in enumerate(nodes, start=1):
        fname = node.metadata.get("source") or node.metadata.get("file_name") or ""
        parts.append(f"[{i}] {fname}\n{node.text[:1000]}")
    context = "\n\n---\n\n".join(parts)

    history_text = ""
    if chat_history:
        lines = []
        for msg in chat_history[-6:]:
            role = "Пользователь" if msg.get("role") == "user" else "Ассистент"
            lines.append(f"{role}: {msg.get('content', '')}")
        history_text = "История диалога:\n" + "\n".join(lines) + "\n\n"

    return (
        f"{history_text}"
        f"Контекст:\n\n{context}\n\n"
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
            http_client=None,
        )
        Settings.llm = LlamaOpenAI(
            model=s.llm.default_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
            temperature=0.0,
            system_prompt=SYSTEM_PROMPT,
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
        self._use_reranker: bool = bool(s.cohere_api_key)

    def build(self) -> None:
        vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=COLLECTION,
        )
        existing = {c.name for c in self._client.get_collections().collections}
        if COLLECTION in existing:
            self._index = VectorStoreIndex.from_vector_store(vector_store)
        else:
            raise RuntimeError(
                f"Коллекция {COLLECTION!r} не найдена. "
                "Сначала запустите: python scripts/ingest.py data/"
            )

    def retrieve_context(self, question: str, chat_history: list[dict] | None = None) -> str:
        """Только retrieval без LLM: возвращает пронумерованный контекст или ''."""
        if self._index is None:
            return ""
        retrieval_question = question
        if chat_history:
            retrieval_question = self._condense(question, chat_history)
        retriever = self._index.as_retriever(similarity_top_k=self._top_k)
        nodes = retriever.retrieve(retrieval_question)
        if not nodes:
            return ""
        if self._use_reranker:
            try:
                from app.services.reranker import rerank
                texts = [n.text for n in nodes]
                sources_list = [n.metadata.get("source", "") for n in nodes]
                ranked = rerank(retrieval_question, texts, sources_list, top_n=5)
                idx_map = {n.text: n for n in nodes}
                reranked = [idx_map[r.text] for r in ranked if r.text in idx_map]
                nodes = reranked if reranked else nodes[:5]
            except Exception:
                nodes = nodes[:5]
        else:
            nodes = nodes[:5]
        top_score = nodes[0].score if nodes else 0.0
        if top_score < self._threshold:
            return ""
        parts = []
        for i, node in enumerate(nodes, start=1):
            fname = node.metadata.get("source") or node.metadata.get("file_name") or ""
            parts.append(f"[{i}] {fname}\n{node.text[:1000]}")
        return "\n\n---\n\n".join(parts) 
    
    
    def _condense(self, question: str, chat_history: list[dict]) -> str:
        if len(question.split()) > 6:
            return question
        lines = [f"{m.get('role','')}: {m.get('content','')}" for m in chat_history[-4:]]
        prompt = (
            "История:\n" + "\n".join(lines) +
            f"\n\nТекущий вопрос: {question}\n\n"
            "Перепиши вопрос как самодостаточный (без ссылок на историю). "
            "Только вопрос, без пояснений."
        )
        return str(Settings.llm.complete(prompt)).strip()

    def answer(self, question: str, chat_history: list[dict] | None = None) -> dict:
        if self._index is None:
            raise RuntimeError("RAGService не инициализирован — вызови build() сначала")

        retrieval_question = question
        if chat_history:
            retrieval_question = self._condense(question, chat_history)

        retriever = self._index.as_retriever(similarity_top_k=self._top_k)
        nodes = retriever.retrieve(retrieval_question)

        if self._use_reranker and nodes:
            try:
                from app.services.reranker import rerank
                texts = [n.text for n in nodes]
                sources_list = [n.metadata.get("source", "") for n in nodes]
                ranked = rerank(retrieval_question, texts, sources_list, top_n=5)
                idx_map = {n.text: n for n in nodes}
                reranked_nodes = []
                for r in ranked:
                    node = idx_map.get(r.text)
                    if node:
                        node.score = r.relevance_score
                        reranked_nodes.append(node)
                nodes = reranked_nodes if reranked_nodes else nodes[:5]
            except Exception:
                nodes = nodes[:5]
        else:
            nodes = nodes[:5]

        top_score = nodes[0].score if nodes else 0.0
        confident = top_score >= self._threshold

        if not confident:
            return {
                "answer": "По базе не нашёл, могу эскалировать.",
                "top_score": round(top_score, 4),
                "confident": False,
                "sources": _format_sources(nodes),
            }

        prompt = _build_prompt(question, nodes, chat_history)
        answer_text = str(Settings.llm.complete(prompt))

        return {
            "answer": answer_text,
            "top_score": round(top_score, 4),
            "confident": True,
            "sources": _format_sources(nodes),
        }


    def evaluate_inputs(self, question: str) -> dict:
        """Для eval-пайплайна: возвращает answer + полный список retrieved_contexts."""
        if self._index is None:
            raise RuntimeError("RAGService не инициализирован — вызови build() сначала")

        retriever = self._index.as_retriever(similarity_top_k=self._top_k)
        nodes = retriever.retrieve(question)

        if self._use_reranker and nodes:
            try:
                from app.services.reranker import rerank
                texts = [n.text for n in nodes]
                sources_list = [n.metadata.get("source", "") for n in nodes]
                ranked = rerank(question, texts, sources_list, top_n=5)
                idx_map = {n.text: n for n in nodes}
                reranked_nodes = []
                for r in ranked:
                    node = idx_map.get(r.text)
                    if node:
                        node.score = r.relevance_score
                        reranked_nodes.append(node)
                nodes = reranked_nodes if reranked_nodes else nodes[:5]
            except Exception:
                nodes = nodes[:5]
        else:
            nodes = nodes[:5]

        retrieved_contexts = [n.text for n in nodes]  # полный текст, не обрезанный

        top_score = nodes[0].score if nodes else 0.0
        if top_score < self._threshold:
            return {
                "answer": "По базе не нашёл, могу эскалировать.",
                "retrieved_contexts": retrieved_contexts,
            }

        prompt = _build_prompt(question, nodes)
        answer_text = str(Settings.llm.complete(prompt))
        return {
            "answer": answer_text,
            "retrieved_contexts": retrieved_contexts,
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
    r1 = svc.answer("Какова неустойка за просрочку оплаты по договору подряда?")
    print("Вопрос 1:", json.dumps(r1["answer"], ensure_ascii=False))
    r2 = svc.answer("а для них?", chat_history=[
        {"role": "user", "content": "Какова неустойка за просрочку оплаты по договору подряда?"},
        {"role": "assistant", "content": r1["answer"]},
    ])
    print("Вопрос 2 (follow-up):", json.dumps(r2["answer"], ensure_ascii=False))