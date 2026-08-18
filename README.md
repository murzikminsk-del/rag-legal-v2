# ИИ-ассистент для анализа юридических документов

## Блок 3.5 — Docker и контейнеризация

Multi-stage Docker-образ, compose-стек с Redis, health/readiness эндпоинты.

**Что реализовано:**
- `Dockerfile` — двухэтапная сборка: builder (uv + зависимости) → runtime (только `/app`); non-root `appuser uid=1000`; BuildKit cache mount для uv; HEALTHCHECK через `urllib.request`
- `.dockerignore` — исключены `.env`, `.git`, `tests/`, `__pycache__`, venv
- `compose.yaml` — сервисы `app` + `redis`; `depends_on: condition: service_healthy`; named volume `redis_data`; Redis без `ports:`
- `app/routers/health.py` — добавлен `GET /ready`: пингует Redis с таймаутом 2s, возвращает 200 `{"redis":"up"}` или 503 `{"redis":"down"}`

**Результаты:**
- Образ: 251 MB (лимит 500 MB)
- Повторный build после правки `app/`: ~10s (слой `uv sync` закеширован)
- `docker compose exec app id` → `uid=1000(appuser)`
- `/health` — 200 всегда; `/ready` — 200 при живом Redis, 503 при остановленном

**Запуск:**
```bash
docker compose up -d --build
```

**Проверка:**
```bash
# Liveness
curl http://localhost:8000/health -UseBasicParsing

# Readiness
curl http://localhost:8000/ready -UseBasicParsing

# Non-root
docker compose exec app id

# Нет секретов в образе
docker run --rm llm-service:v1 ls -la /app
```

---

## Блок 3.4 — FastAPI-сервис для LLM

Production-структура поверх async-клиента из блока 3.3: DI, Redis-кеш, middleware, Swagger.

**Что реализовано:**
- `app/core/config.py` — `Settings` с вложенным `LLMSettings`, `redis_url`, `cache_ttl_seconds`, `cors_origins`
- `app/core/exceptions.py` — доменные исключения `LLMError` / `LLMRateLimitError` / `LLMTimeoutError` / `LLMAuthError`
- `app/deps/providers.py` — DI через `Depends`: `get_openai`, `get_cache`, `get_llm_service` + `Annotated` type-aliases
- `app/schemas/chat.py` — `ChatRequest`, `ChatResponse.from_openai()`, `ChatDelta`
- `app/schemas/models.py` — статический список моделей OpenAI с ценами
- `app/services/llm.py` — `LLMService.complete()` с Redis-кешем (sha256 ключ) + `stream()` AsyncGenerator
- `app/routers/chat.py` — `POST /chat` (sync) + `POST /chat/stream` (StreamingResponse, SSE руками)
- `app/routers/health.py` — `GET /health` без зависимостей
- `app/routers/models.py` — `GET /models`
- `app/main.py` — lifespan (OpenAI + Redis), CORSMiddleware, request_logging middleware, exception handlers

**Результаты:**
- Cache hit: 4ms vs 2634ms первого запроса
- При сломанном ключе: 502 `llm_auth`, не 500 с traceback

**Запуск:**
```bash
uvicorn app.main:app --reload
```

**Проверка POST /chat:**
```bash
# создать body.json один раз:
echo '{"messages":[{"role":"user","content":"hi"}]}' > body.json
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "@body.json"
```

**Проверка стриминга:**
```bash
curl -N -X POST http://localhost:8000/chat/stream -H "Content-Type: application/json" -d "@body.json"
```

**Swagger:** http://localhost:8000/docs

---

## Блок 3.3 — Асинхронная обработка запросов к ИИ

Синхронный клиент переведён на `asyncio`. Добавлен FastAPI-сервер с SSE-стримингом.

**Что реализовано:**
- `app/services/llm_client.py` — класс `AsyncLLMClient`:
  - `complete` — одиночный async-вызов с `asyncio.timeout(15)`, `Semaphore`, логом `llm.call`
  - `batch_chat` — параллельный запуск через `asyncio.gather(..., return_exceptions=True)`
  - `stream_chat` — async-генератор, yield-ит токены по мере прихода, логирует TTFT и total_tokens
- `app/api/routes.py` + `app/main.py` — FastAPI SSE-эндпоинт `POST /chat/stream`
- `scripts/benchmark.py` — замер sync vs async

**Результаты бенчмарка (20 запросов):**

| Режим | Время | Ускорение |
|---|---|---|
| Sync sequential | 37.11s | 1x |
| Async concurrency=1 | 32.66s | ~1x |
| Async concurrency=5 | 15.02s | 2.5x |
| Async concurrency=10 | 4.44s | **8.4x** |

**Запуск сервера:**
```bash
uvicorn app.main:app --reload
```

**Проверка SSE:**
```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Что такое event loop?"}'
```

**Запуск бенчмарка:**
```bash
$env:PYTHONPATH = "."; python scripts/benchmark.py
```

---

## Блок 3.2 — Архитектурный паспорт

Создан `docs/architecture.md` — архитектурный паспорт проекта на ближайшие 4 модуля.

**Содержит:**
- Mermaid-диаграмма 4 слоёв: API Gateway → Service → LLM → Data
- Circuit Breaker на каждом LLM-провайдере (aiobreaker, fail_max=5, timeout=60s)
- Fallback chain: OpenAI gpt-4o-mini → Anthropic claude-haiku-4-5 → Ollama llama3.1:8b
- Cache-Aside: Redis, TTL 1h, key: sha256(model + messages + temperature=0)
- ADR-001: выбор паттерна Request-Response
- ADR-002: стратегия fault tolerance
- Потенциальные точки отказа — все 4 слоя с graceful degradation

## Блок 3.1 — Function Calling

Реализован инструмент `search_documents(query, doc_type)` — поиск по локальной базе юридических документов (`data/documents.json`).

### Структура проекта
```
rag-legal-v2/
├── app/
│   ├── api/
│   │   └── routes.py           # SSE-эндпоинт POST /chat/stream
│   ├── services/
│   │   └── llm_client.py       # AsyncLLMClient (complete, batch_chat, stream_chat)
│   ├── prompts/
│   │   ├── tools/
│   │   │   └── search_docs.md  # description инструмента
│   │   ├── loader.py           # загрузчик промптов
│   │   └── system_v1.j2        # системный промпт (Jinja2-шаблон)
│   ├── tools/
│   │   ├── handlers.py         # функция-обработчик (читает data/documents.json)
│   │   └── schemas.py          # JSON Schema инструмента
│   ├── llm/
│   │   └── client.py           # sync tool_call цикл (блок 3.1)
│   ├── main.py                 # FastAPI приложение
│   └── config.py               # настройки через pydantic-settings
├── data/
│   └── documents.json          # база знаний: 5 юридических документов
├── scripts/
│   └── benchmark.py            # замер sync vs async
├── examples/
│   └── run_tool_call.py        # три тест-кейса
├── tests/
│   └── test_tool_call.py       # 4 unit-теста без API
├── docs/
│   └── architecture.md         # архитектурный паспорт проекта
├── .env.example
└── pyproject.toml
```


### Запуск тестов (без API-ключа)

```bash
uv run pytest tests/ -v

Запуск примеров
$env:PYTHONPATH = "."; uv run python examples/run_tool_call.py
Три тест-кейса

(а) Запрос требует tool

Запрос: Найди договор аренды и скажи какой депозит.

Модель вызвала search_documents с аргументами query="договор аренды", doc_type="contract". Найден contract_002. Финальный ответ: «Депозит по договору аренды офиса №7/2024 составляет 170 000 рублей.»

(б) Запрос не требует tool

Запрос: Что такое неустойка простыми словами?

Модель не вызвала инструмент — вопрос общий, ответ сформирован текстом. Код не упал.

(в) Пограничный случай

Запрос: Есть ли у нас документы про персональные данные?

Модель правильно решила вызвать search_documents. Однако поиск не нашёл документ: в базе написано «персональных данных», а модель передала «персональные данные» — разные падежи, точное вхождение подстроки не совпало. Ограничение метода поиска без морфологии.