"""
Реранкер на основе Cohere Rerank API.
Принимает вопрос и список чанков, возвращает их переупорядоченными.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cohere

from app.core.config import get_settings


@dataclass
class RankedResult:
    text: str
    source: str
    original_index: int
    relevance_score: float


def get_cohere_client() -> cohere.Client:
    import httpx

    api_key = os.environ.get("COHERE_API_KEY") or ""
    if not api_key:
        s = get_settings()
        api_key = getattr(s, "cohere_api_key", "") or ""
    if not api_key:
        raise RuntimeError("COHERE_API_KEY не задан")

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        http_client = httpx.Client(proxy=proxy, timeout=60.0)
        return cohere.Client(api_key, httpx_client=http_client)
    return cohere.Client(api_key)


def rerank(
    question: str,
    texts: list[str],
    sources: list[str],
    top_n: int | None = None,
    model: str = "rerank-v3.5",
) -> list[RankedResult]:
    """
    Реранкует тексты по отношению к вопросу.

    texts и sources должны быть одинаковой длины.
    Возвращает результаты, отсортированные по relevance_score убыванию.
    """
    if not texts:
        return []

    client = get_cohere_client()
    response = client.rerank(
        model=model,
        query=question,
        documents=texts,
        top_n=top_n or len(texts),
    )

    results = []
    for item in response.results:
        idx = item.index
        results.append(
            RankedResult(
                text=texts[idx],
                source=sources[idx],
                original_index=idx,
                relevance_score=item.relevance_score,
            )
        )
    return results