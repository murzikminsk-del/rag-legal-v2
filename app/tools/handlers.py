import json
from pathlib import Path

# Путь к файлу с документами
# Path(__file__) — текущий файл (handlers.py)
# .parent.parent.parent — поднимаемся на три уровня вверх: tools → app → rag-legal-v2
# / "data" / "documents.json" — спускаемся в data/documents.json
DOCUMENTS_PATH = Path(__file__).parent.parent.parent / "data" / "documents.json"


def search_documents(query: str, doc_type: str) -> str:
    # Читаем весь файл documents.json и превращаем в список Python-словарей
    documents = json.loads(DOCUMENTS_PATH.read_text(encoding="utf-8"))

    # Приводим поисковый запрос к нижнему регистру для регистронезависимого поиска
    query_lower = query.lower()

    results = []
    for doc in documents:
        # Если doc_type не "any" — фильтруем по типу документа
        if doc_type != "any" and doc["doc_type"] != doc_type:
            continue

        # Проверяем: встречается ли запрос в заголовке или аннотации документа
        # Ищем в title и summary — оба приводим к нижнему регистру
        if query_lower in doc["title"].lower() or query_lower in doc["summary"].lower():
            results.append(doc)

    # Если ничего не нашли — возвращаем честный ответ
    if not results:
        return f"Документы по запросу '{query}' не найдены."

    # Формируем текстовый ответ — модель получит его и напишет финальный ответ
    lines = [f"Найдено документов: {len(results)}\n"]
    for doc in results:
        lines.append(f"ID: {doc['id']}")
        lines.append(f"Название: {doc['title']}")
        lines.append(f"Тип: {doc['doc_type']}")
        lines.append(f"Стороны: {', '.join(doc['parties'])}")
        lines.append(f"Дата: {doc['date']}")
        lines.append(f"Содержание: {doc['summary']}")
        lines.append("")  # пустая строка между документами

    return "\n".join(lines)