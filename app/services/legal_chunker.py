"""Чанкер для юридических документов: режет по разделам и пунктам, а не по длине.

Вход — текст документа построчно (как его отдаёт DocxWithTablesReader):
абзацы — отдельными строками, строки таблиц — ячейки через « | ».

Правила:
- «6. Срок действия» / «I. Общие положения» — заголовок раздела (запоминаем);
- «6.1.» / «1.5.1» — начало пункта; всё до следующего номера — тот же пункт;
- строки таблицы держим вместе, в каждый кусок таблицы повторяем её шапку;
- чанк = целые пункты до MAX_CHARS; пункт режем, только если он сам длиннее;
- к каждому чанку — шапка «договор · файл · Раздел: …».
"""

from __future__ import annotations

import re
from dataclasses import dataclass


from llama_index.core.node_parser import NodeParser
from llama_index.core.node_parser.node_utils import build_nodes_from_splits
from llama_index.core.schema import BaseNode

MAX_CHARS = 1800
# чанк короче — приклеиваем к соседу: иначе его вектор почти целиком состоит
# из шапки «договор · файл · раздел» и он всплывает на любой вопрос по договору
MIN_CHARS = 500

# «6.» / «6. Срок…» / «I. Общие…» — номер раздела верхнего уровня
SECTION_RE = re.compile(r"^(?:\d{1,2}|[IVXLC]{1,6})\.(?:\s+(?P<title>\S.*))?$")
# «6.1.» / «1.5.1» / «17.9.9. Если…» — номер пункта
CLAUSE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,4}\.?(?:\s|$)")
TABLE_SEP = " | "
MAX_TITLE_CHARS = 150  # длиннее — это уже не заголовок, а пункт с текстом


@dataclass
class Block:
    """Неделимый кусок: пункт целиком или группа строк таблицы."""
    section: str
    lines: list[str]
    table_header: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _join_lone_numbers(lines: list[str]) -> list[str]:
    """«6.» + «Срок действия» на соседних строках → «6. Срок действия»."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.fullmatch(r"(?:\d{1,2}(?:\.\d{1,3}){0,4}|[IVXLC]{1,6})\.?", line) and i + 1 < len(lines):
            out.append(f"{line} {lines[i + 1]}")
            i += 2
            continue
        out.append(line)
        i += 1
    return out


def _is_section(line: str) -> str | None:
    """Название раздела, если строка — заголовок раздела, иначе None."""
    if TABLE_SEP in line or len(line) > MAX_TITLE_CHARS:
        return None
    m = SECTION_RE.match(line)
    if not m:
        return None
    title = m.group("title") or ""
    # «1. Настоящее Положение разработано …» — это пункт с текстом, не заголовок
    if title.endswith((".", ";", ":")) and len(title) > 60:
        return None
    return line


def _to_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    section = ""
    cur: Block | None = None

    def flush() -> None:
        nonlocal cur
        if cur and cur.lines:
            blocks.append(cur)
        cur = None

    lines = _join_lone_numbers(lines)
    for i, line in enumerate(lines):
        # строка без « | » между двумя строками таблицы — объединённая ячейка
        # (подзаголовок группы строк), она тоже часть таблицы
        in_table = TABLE_SEP in line or (
            0 < i < len(lines) - 1
            and TABLE_SEP in lines[i - 1]
            and TABLE_SEP in lines[i + 1]
        )
        if in_table:
            if cur is None or cur.table_header is None:
                flush()
                # первая строка таблицы — её шапка
                cur = Block(section, [line], table_header=line)
            else:
                cur.lines.append(line)
            continue
        title = _is_section(line)
        if title:
            flush()
            section = title
            cur = Block(section, [line])
            continue
        if CLAUSE_RE.match(line) or cur is None or cur.table_header is not None:
            flush()
            cur = Block(section, [line])
        else:
            cur.lines.append(line)  # подпункт (а), (б) или продолжение пункта
    flush()
    return blocks


def _split_long(block: Block) -> list[Block]:
    """Режет блок длиннее MAX_CHARS по строкам (таблица — с повтором шапки)."""
    if len(block.text) <= MAX_CHARS:
        return [block]
    parts: list[Block] = []
    head = block.table_header
    first = block.lines[0]
    cur: list[str] = []
    for line in block.lines:
        if cur and len("\n".join(cur)) + len(line) > MAX_CHARS:
            parts.append(Block(block.section, cur, head))
            if head:
                cur = [head] if line != head else []
            else:
                num = first.split()[0] if CLAUSE_RE.match(first) else ""
                cur = [f"(продолжение п. {num.rstrip('.')})"] if num else []
        cur.append(line)
    if cur:
        parts.append(Block(block.section, cur, head))
    return parts


def chunk_legal_text(text: str, doc_title: str) -> list[dict]:
    """Текст документа → чанки [{text, section}] с шапкой в начале текста."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    blocks = [b for blk in _to_blocks(lines) for b in _split_long(blk)]

    groups: list[list[Block]] = []
    buf: list[Block] = []

    def emit() -> None:
        if buf:
            groups.append(list(buf))
            buf.clear()

    for b in blocks:
        size = sum(len(x.text) for x in buf)
        is_table = b.table_header is not None
        # новый раздел, граница «таблица/текст» или переполнение — закрываем чанк
        if buf and (
            b.section != buf[0].section
            or is_table != (buf[0].table_header is not None)
            or size + len(b.text) > MAX_CHARS
        ):
            emit()
        buf.append(b)
    emit()

    # мелкие группы приклеиваем к соседней — но только внутри того же раздела
    # (подписи к таблице, хвост пункта); короткий самостоятельный раздел остаётся
    # отдельным чанком. Преамбула до первого раздела (титульный лист) — к первому разделу.
    def size(g: list[Block]) -> int:
        return sum(len(b.text) for b in g)

    merged: list[list[Block]] = []
    for g in groups:
        prev = merged[-1] if merged else None
        fits = prev is not None and size(prev) + size(g) <= MAX_CHARS * 1.5
        same_section = prev is not None and prev[0].section == g[0].section
        if fits and size(g) < MIN_CHARS and same_section:
            prev.extend(g)  # мелкий хвост — к предыдущему
        elif fits and size(prev) < MIN_CHARS and (same_section or not prev[0].section):
            prev.extend(g)  # мелкий предыдущий (или преамбула) — к текущему
        else:
            merged.append(g)

    chunks: list[dict] = []
    for g in merged:
        section = next((b.section for b in g if b.section), "")
        header = f"[{doc_title}" + (f" · Раздел: {section}" if section else "") + "]"
        body = "\n".join(b.text for b in g)
        chunks.append({"text": f"{header}\n{body}", "section": section})
    return chunks



class LegalNodeParser(NodeParser):
    """Обёртка для IngestionPipeline: документ LlamaIndex → чанки chunk_legal_text."""

    def _parse_nodes(self, nodes, show_progress: bool = False, **kwargs) -> list[BaseNode]:
        out: list[BaseNode] = []
        for doc in nodes:
            meta = doc.metadata
            title = " · ".join(x for x in (meta.get("category"), meta.get("source")) if x)
            chunks = chunk_legal_text(doc.get_content(), title)
            built = build_nodes_from_splits([c["text"] for c in chunks], doc, id_func=self.id_func)
            for node, c in zip(built, chunks):
                node.metadata["section"] = c["section"]
                # шапка «договор · файл · раздел» уже в тексте чанка — метаданные
                # не дублируем ни в эмбеддинг, ни в промпт LLM
                hidden = [*meta, "section"]
                node.excluded_embed_metadata_keys = hidden
                node.excluded_llm_metadata_keys = hidden
            out.extend(built)
        return out