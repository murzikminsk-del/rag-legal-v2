# Vector Store — документация

## Метрика

### Cosine vs Dot product — эксперимент

Модель: `text-embedding-3-small` (OpenAI). Векторы L2-нормализованы библиотекой.

| Запрос | Cosine top-5 (chunk_id) | Dot top-5 (chunk_id) | Совпадение |
|--------|------------------------|----------------------|------------|
| Как расторгнуть договор аренды досрочно? | 06a165d0, 27ebb3da, 7f37d854, da7ec4a8, 54679e61 | 06a165d0, 27ebb3da, 7f37d854, da7ec4a8, 54679e61 | ✓ |
| Какова неустойка за просрочку выполнения работ? | 7e97e5c0, 48561461, 479db8d3, e41c6154, a8664ef3 | 7e97e5c0, 48561461, 479db8d3, e41c6154, a8664ef3 | ✓ |
| Какие данные относятся к коммерческой тайне? | d7463744, d515ad3f, a5cacaf6, 3273e3f6, dcb7edc6 | d7463744, d515ad3f, a5cacaf6, 3273e3f6, dcb7edc6 | ✓ |
| Кто вправе подписывать договоры свыше 5 млн? | 811723fd, a4caf17d, 69639ffa, 8c0210e2, 1a1ddca0 | 811723fd, a4caf17d, 69639ffa, 8c0210e2, 1a1ddca0 | ✓ |
| Какова ответственность за нарушение NDA? | 47bddf9a, d70de970, b740f929, d515ad3f, c2de6872 | 47bddf9a, d70de970, b740f929, d515ad3f, c2de6872 | ✓ |

**Вывод:** `text-embedding-3-small` возвращает L2-нормализованные векторы, поэтому
cosine similarity и dot product дают идентичное ранжирование (для нормализованных
векторов cosine = dot / (|a|·|b|) = dot).

**Выбор в production: COSINE.** Причины:
- Семантически интуитивен: значение от -1 до 1, независимо от длины вектора
- При смене модели на ненормализованную (например, локальную) поведение останется корректным
- Qdrant рекомендует COSINE для текстовых эмбеддингов

Обе временные коллекции (`documents_cosine`, `documents_dot`) удалены после эксперимента.
В production остаётся одна боевая коллекция — `documents`.

## Фильтрация по metadata

### 1. Match по строке (category = "nda")

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

query_filter = Filter(
    must=[
        FieldCondition(key="category", match=MatchValue(value="nda"))
    ]
)
results = await vector_store.search(query_vector=vec, top_k=3, query_filter=query_filter)
```

Top-3 результата (запрос: «ответственность за разглашение конфиденциальной информации»):

1. `nda_001_2` — штраф 500 000 руб. за каждый факт разглашения
2. `nda_002_1` — уничтожение носителей после истечения срока
3. `nda_003_1` — субподрядчики включаются в периметр NDA

---

### 2. Range по дате (created_at >= 2025-01-01)

```python
from datetime import datetime, timezone
from qdrant_client.models import Filter, FieldCondition, DatetimeRange

query_filter = Filter(
    must=[
        FieldCondition(
            key="created_at",
            range=DatetimeRange(gte=datetime(2025, 1, 1, tzinfo=timezone.utc))
        )
    ]
)
results = await vector_store.search(query_vector=vec, top_k=3, query_filter=query_filter)
```

Top-3 результата (запрос: «обработка персональных данных»):

- **Без фильтра:** первым идёт `policy_001_0` (2024-02-01) — старая политика ПДн
- **С фильтром:** первым идёт `policy_002_0` (2025-01-15) — обновлённая политика 2025 года с требованиями по ИИ-системам

---

### 3. Композитный must + must_not

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

query_filter = Filter(
    must=[
        FieldCondition(key="category", match=MatchValue(value="contract"))
    ],
    must_not=[
        FieldCondition(key="source", match=MatchValue(value="contract_002.md"))
    ]
)
results = await vector_store.search(query_vector=vec, top_k=3, query_filter=query_filter)
```

Смысл: «только договоры, исключая договор аренды» — типичный паттерн production-RAG,
когда нужно ограничить выдачу тематикой пользователя, исключив нерелевантные источники.

Top-3 результата (запрос: «неустойка за просрочку»):

1. `contract_001_2` — неустойка 0,1%/день по договору подряда
2. `claim_003_1` — расчёт неустойки по договору разработки ПО
3. `contract_003_1` — гарантийные условия договора поставки
