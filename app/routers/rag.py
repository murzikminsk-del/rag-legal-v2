import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.services.ingestion import get_ingestion_service

router = APIRouter(prefix="/rag", tags=["rag"])

UPLOAD_DIR = Path("var/uploads")


class RAGQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    chat_history: list[dict] | None = None  # [{"role": "user"|"assistant", "content": "..."}]


class RAGSource(BaseModel):
    id: int
    file_name: str
    category: str
    page: int | str | None
    score: float
    snippet: str


class RAGAnswer(BaseModel):
    answer: str
    top_score: float
    confident: bool
    sources: list[RAGSource]


@router.post("/query", response_model=RAGAnswer)
async def rag_query(body: RAGQuery, request: Request):
    rag = getattr(request.app.state, "rag", None)
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG-индекс недоступен")
    result = rag.answer(body.question, chat_history=body.chat_history)
    return result


def _ingest_uploaded(file_path: Path) -> None:
    svc = get_ingestion_service()
    try:
        svc.ingest_file(file_path)
    except Exception as exc:
        failed = file_path.with_suffix(file_path.suffix + ".failed")
        file_path.rename(failed)
        raise RuntimeError(f"Ошибка индексации {file_path.name}: {exc}") from exc


@router.post("/documents/upload", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    allowed = {".md", ".pdf", ".docx", ".html", ".htm"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Формат {suffix!r} не поддерживается. Допустимые: {sorted(allowed)}",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / file.filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    background_tasks.add_task(_ingest_uploaded, dest)
    return {"status": "accepted", "file": file.filename}