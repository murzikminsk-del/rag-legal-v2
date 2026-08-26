from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/rag", tags=["rag"])


class RAGQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RAGSource(BaseModel):
    text: str
    source: str | None
    score: float


class RAGAnswer(BaseModel):
    answer: str
    top_score: float
    sources: list[RAGSource]


@router.post("/query", response_model=RAGAnswer)
async def rag_query(body: RAGQuery, request: Request):
    rag = getattr(request.app.state, "rag", None)
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG-индекс недоступен")
    result = rag.answer(body.question)
    return result