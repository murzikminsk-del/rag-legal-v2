from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from llama_index.core import Document
from llama_index.core.node_parser import (
    TokenTextSplitter,
    SentenceSplitter,
    SemanticSplitterNodeParser,
)


@dataclass
class Chunk:
    text: str
    source: str
    chunk_index: int


Strategy = Literal["fixed_size", "recursive", "semantic"]


def _ru_sentence_tokenizer(text: str) -> list[str]:
    """Простой токенизатор предложений для русского текста."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def chunk_text_sync(
    text: str,
    source: str,
    strategy: Strategy,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[Chunk]:
    doc = Document(text=text, metadata={"source": source})

    if strategy == "fixed_size":
        splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        nodes = splitter.get_nodes_from_documents([doc])

    elif strategy == "recursive":
        splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            paragraph_separator="\n\n",
            chunking_tokenizer_fn=_ru_sentence_tokenizer,
        )
        nodes = splitter.get_nodes_from_documents([doc])

    else:
        raise ValueError(f"Для стратегии '{strategy}' используй chunk_text_async")

    return [
        Chunk(text=node.get_content(), source=source, chunk_index=i)
        for i, node in enumerate(nodes)
        if node.get_content().strip()
    ]


async def chunk_text_async(
    text: str,
    source: str,
    strategy: Strategy,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
) -> list[Chunk]:
    if strategy != "semantic":
        return chunk_text_sync(text, source, strategy, chunk_size, chunk_overlap)

    from llama_index.core import Settings as LISettings
    from llama_index.core.node_parser import TokenTextSplitter
    from llama_index.embeddings.openai import OpenAIEmbedding
    from app.core.config import get_settings

    cfg = get_settings()
    embed_model = OpenAIEmbedding(
        model=cfg.embedding_model,
        api_key=cfg.llm.openai_api_key.get_secret_value(),
    )

    splitter = SemanticSplitterNodeParser(
        buffer_size=1,
        breakpoint_percentile_threshold=95,
        embed_model=embed_model,
    )
    # вторичный сплиттер для слишком длинных чанков
    fallback = TokenTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    doc = Document(text=text, metadata={"source": source})
    raw_nodes = splitter.get_nodes_from_documents([doc])

    # дробим чанки, превышающие chunk_size токенов
    final_nodes = []
    for node in raw_nodes:
        content = node.get_content().strip()
        if not content:
            continue
        sub_nodes = fallback.get_nodes_from_documents([Document(text=content)])
        final_nodes.extend(sub_nodes)

    return [
        Chunk(text=node.get_content(), source=source, chunk_index=i)
        for i, node in enumerate(final_nodes)
        if node.get_content().strip()
    ]