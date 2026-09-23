"""Одноразовая подготовка docx для индексации (нужен установленный Word).

1. Автонумерацию Word превращает в обычный текст — иначе номера пунктов
   («5.3.1», «(а)») не попадают в индекс.
2. В «КС Вологда.docx» таблицу-вёрстку превращает в обычные абзацы.
   В приложениях таблицы НЕ трогаем — там это настоящие таблицы.

Запуск: uv run --with pywin32 python scripts/convert_numbering.py
"""
from pathlib import Path

import win32com.client

LAYOUT_TABLE_FILES = {"КС Вологда.docx"}
WD_SEPARATE_BY_PARAGRAPHS = 0

word = win32com.client.Dispatch("Word.Application")
word.Visible = False
try:
    for f in sorted(Path("data").rglob("*.docx")):
        if f.name.startswith("~$"):  # временные файлы Word
            continue
        doc = word.Documents.Open(str(f.resolve()))
        if f.name in LAYOUT_TABLE_FILES:
            # с конца, чтобы номера оставшихся таблиц не сдвигались
            for i in range(doc.Tables.Count, 0, -1):
                doc.Tables(i).ConvertToText(
                    Separator=WD_SEPARATE_BY_PARAGRAPHS, NestedTables=True
                )
        doc.ConvertNumbersToText()
        doc.Save()
        doc.Close()
        print("✓", f)
finally:
    word.Quit()