import pytest

from app.tools.handlers import search_documents


def test_search_finds_existing_document():
    # Проверяем: запрос "аренда" находит договор аренды
    result = search_documents(query="аренда", doc_type="any")

    # В результате должно быть название договора
    assert "Договор аренды" in result


def test_search_by_doc_type_filters_correctly():
    # Проверяем: фильтр по типу работает
    # Ищем только policy — должна найтись политика персональных данных
    result = search_documents(query="персональных", doc_type="policy")

    assert "policy_001" in result


def test_search_returns_not_found_message():
    # Проверяем: если документа нет — возвращается понятное сообщение
    result = search_documents(query="космические корабли", doc_type="any")

    assert "не найдены" in result


def test_search_wrong_doc_type_returns_not_found():
    # Проверяем: договор аренды есть, но ищем среди claim — не найдётся
    result = search_documents(query="аренда", doc_type="claim")

    assert "не найдены" in result