"""
Индексирует корпус data/ в Qdrant с помощью IngestionPipeline.
Поддерживает форматы: MD, PDF, DOCX, HTML.
Упавшие файлы переименовываются в .failed и фиксируются в логах.

Запуск:
    python scripts/ingest.py data/
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,qdrant")

from llama_index.core import Settings, SimpleDirectoryReader
from llama_index.core.ingestion import IngestionPipeline, DocstoreStrategy
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.readers.file import (
    PyMuPDFReader,
    
    HTMLTagReader,
    MarkdownReader,
)
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.core.config import get_settings

from llama_index.core.readers.base import BaseReader
from llama_index.core import Document


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxWithTablesReader(BaseReader):
    """Читает DOCX: обычные абзацы и таблицы (построчно, ячейки через ' | ')."""

    @staticmethod
    def _para_text(p) -> str:
        """Текст одного абзаца <w:p>; табуляция и перенос строки → пробел."""
        out = []
        for node in p.iter(W + "t", W + "tab", W + "br"):
            if node.tag == W + "t":
                out.append(node.text or "")
            else:
                out.append(" ")
        return " ".join("".join(out).split())

    def _cell_text(self, cell) -> str:
        """Текст ячейки: абзацы через перенос строки, а не слитно."""
        paras = [self._para_text(p) for p in cell.iter(W + "p")]
        return "\n".join(p for p in paras if p)

    def load_data(self, file, extra_info=None):
        from docx import Document as DocxDocument

        doc = DocxDocument(file)
        parts = []
        for block in doc.element.body:
            if block.tag == W + "p":
                text = self._para_text(block)
                if text:
                    parts.append(text)
            elif block.tag == W + "tbl":
                # только строки и ячейки этого уровня — вложенные таблицы
                # попадут в текст через cell.iter(p) один раз, без дублей
                for row in block.findall(W + "tr"):
                    cells = [self._cell_text(c) for c in row.findall(W + "tc")]
                    cells = [c for c in cells if c]
                    if cells:
                        parts.append(" | ".join(cells))
        text = "\n".join(parts)
        return [Document(text=text, extra_info=extra_info or {})]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DOCSTORE_PATH = "var/docstore.json"
COLLECTION = "rag_legal_v2"

FILE_EXTRACTOR = {
    ".pdf":  PyMuPDFReader(),
    ".docx": DocxWithTablesReader(),
    ".html": HTMLTagReader(),
    ".htm":  HTMLTagReader(),
    ".md":   MarkdownReader(),
}


def _ensure_collection(client: QdrantClient, name: str, dim: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        log.info("Создана коллекция %s", name)


def _load_documents(data_dir: Path) -> list:
    """Загружает документы, помечает упавшие файлы как .failed."""
    docs = []
    for fpath in sorted(data_dir.rglob("*")):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in FILE_EXTRACTOR:
            continue
        try:
            loaded = SimpleDirectoryReader(
                input_files=[str(fpath)],
                file_extractor=FILE_EXTRACTOR,
            ).load_data()
            # metadata-обогащение
            stat = fpath.stat()
            category = fpath.parent.name
            for i, doc in enumerate(loaded):
                doc.doc_id = f"{fpath}:{i}"          # ← добавить эту строку
                doc.metadata["source"] = fpath.name
                doc.metadata["category"] = category
                doc.metadata["last_modified"] = int(stat.st_mtime)
                doc.metadata["file_path"] = str(fpath)
                stem = fpath.stem
                if "_v" in stem:
                    doc.metadata["version"] = stem.split("_v")[-1]
                doc.excluded_embed_metadata_keys = ["last_modified", "file_path"]
            
            docs.extend(loaded)
            log.info("  ✓ %s (%d документов)", fpath.name, len(loaded))
        except Exception as exc:
            failed_path = fpath.with_suffix(fpath.suffix + ".failed")
            fpath.rename(failed_path)
            log.error("  ✗ %s → .failed: %s", fpath.name, exc)
    return docs


def main(data_dir: str) -> None:
    s = get_settings()

    Settings.embed_model = OpenAIEmbedding(
        model=s.embedding_model,
        api_key=s.llm.openai_api_key.get_secret_value(),
    )

    client = QdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        check_compatibility=False,
    )
    _ensure_collection(client, COLLECTION, s.embedding_dim)

    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION)

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
        vector_store=vector_store,
        docstore=docstore,
        docstore_strategy=DocstoreStrategy.UPSERTS_AND_DELETE,
    )

    log.info("Загружаю документы из %s ...", data_dir)
    documents = _load_documents(Path(data_dir))
    log.info("Всего загружено: %d документов", len(documents))

    if not documents:
        log.warning("Документы не найдены. Выход.")
        return

    log.info("Запускаю IngestionPipeline ...")
    nodes = pipeline.run(documents=documents, show_progress=True)
    log.info("Проиндексировано узлов: %d", len(nodes))

    docstore.persist(str(docstore_path))
    log.info("Docstore сохранён: %s", docstore_path)
    log.info("✓ Индексация завершена. Коллекция: %s", COLLECTION)


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    main(data_dir)