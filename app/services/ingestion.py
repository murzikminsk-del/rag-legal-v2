"""
Сервис индексации документов для использования из FastAPI.
Используется в POST /documents/upload через BackgroundTasks.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from llama_index.core import Settings
from llama_index.core.ingestion import DocstoreStrategy, IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core import SimpleDirectoryReader
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.readers.file import DocxReader, HTMLTagReader, MarkdownReader, PyMuPDFReader
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import get_settings

log = logging.getLogger(__name__)

DOCSTORE_PATH = "var/docstore.json"
COLLECTION = "rag_legal_v2"

FILE_EXTRACTOR = {
    ".pdf":  PyMuPDFReader(),
    ".docx": DocxReader(),
    ".html": HTMLTagReader(),
    ".htm":  HTMLTagReader(),
    ".md":   MarkdownReader(),
}


class IngestionService:
    def __init__(self) -> None:
        s = get_settings()
        self._settings = s

        Settings.embed_model = OpenAIEmbedding(
            model=s.embedding_model,
            api_key=s.llm.openai_api_key.get_secret_value(),
        )

        self._client = QdrantClient(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            check_compatibility=False,
        )
        self._vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=COLLECTION,
        )

    def _load_file(self, fpath: Path) -> list:
        suffix = fpath.suffix.lower()
        if suffix not in FILE_EXTRACTOR:
            return []
        docs = SimpleDirectoryReader(
            input_files=[str(fpath)],
            file_extractor=FILE_EXTRACTOR,
        ).load_data()
        stat = fpath.stat()
        category = fpath.parent.name
        for i, doc in enumerate(docs):
            doc.doc_id = f"{fpath}:{i}"
            doc.metadata["source"] = fpath.name
            doc.metadata["category"] = category
            doc.metadata["last_modified"] = int(stat.st_mtime)
            doc.metadata["file_path"] = str(fpath)
            stem = fpath.stem
            if "_v" in stem:
                doc.metadata["version"] = stem.split("_v")[-1]
            # author из DOCX core properties (только для .docx)
            if suffix == ".docx":
                try:
                    from docx import Document as DocxDocument
                    props = DocxDocument(str(fpath)).core_properties
                    if props.author:
                        doc.metadata["author"] = props.author
                except Exception:
                    pass
            doc.excluded_embed_metadata_keys = ["last_modified", "file_path"]
        return docs

    def _build_pipeline(self) -> tuple[IngestionPipeline, SimpleDocumentStore]:
        s = self._settings
        docstore_path = Path(DOCSTORE_PATH)
        docstore_path.parent.mkdir(parents=True, exist_ok=True)
        if docstore_path.exists():
            docstore = SimpleDocumentStore.from_persist_path(str(docstore_path))
        else:
            docstore = SimpleDocumentStore()

        pipeline = IngestionPipeline(
            transformations=[
                SentenceSplitter(
                    chunk_size=s.chunk_size,
                    chunk_overlap=s.chunk_overlap,
                ),
                Settings.embed_model,
            ],
            vector_store=self._vector_store,
            docstore=docstore,
            docstore_strategy=DocstoreStrategy.UPSERTS,
        )
        return pipeline, docstore

    def ingest_file(self, fpath: Path) -> int:
        """Индексирует один файл. Возвращает число новых узлов."""
        docs = self._load_file(fpath)
        if not docs:
            log.warning("Формат не поддерживается: %s", fpath.suffix)
            return 0
        pipeline, docstore = self._build_pipeline()
        nodes = pipeline.run(documents=docs)
        docstore.persist(DOCSTORE_PATH)
        log.info("Проиндексирован файл %s: %d узлов", fpath.name, len(nodes))
        return len(nodes)

    def ingest_dir(self, data_dir: Path) -> int:
        """Индексирует всю директорию. Возвращает число новых узлов."""
        docs = []
        for fpath in sorted(data_dir.rglob("*")):
            if not fpath.is_file() or fpath.suffix.lower() not in FILE_EXTRACTOR:
                continue
            try:
                docs.extend(self._load_file(fpath))
            except Exception as exc:
                failed = fpath.with_suffix(fpath.suffix + ".failed")
                fpath.rename(failed)
                log.error("✗ %s → .failed: %s", fpath.name, exc)
        if not docs:
            return 0
        pipeline, docstore = self._build_pipeline()
        nodes = pipeline.run(documents=docs, show_progress=True)
        docstore.persist(DOCSTORE_PATH)
        return len(nodes)


_ingestion_service: IngestionService | None = None


def get_ingestion_service() -> IngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service