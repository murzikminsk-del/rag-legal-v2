# ИИ-ассистент для анализа юридических документов

## Блок 5.2 — Векторные базы данных

Qdrant как хранилище эмбеддингов: коллекция с payload-индексами, загрузка 100+ документов, поиск с фильтрами.

**Что реализовано:**
- `compose.yaml` — сервис `qdrant` (образ `qdrant/qdrant:v1.14.0`, порты 6333/6334, named volume `qdrant_storage`, healthcheck по TCP, API-ключ из `.env`)
- `app/core/config.py` — добавлены `qdrant_url`, `qdrant_api_key`, `qdrant_collection`, `embedding_dim`
- `app/services/vector_store.py` — `VectorStore`: тонкая обёртка над `AsyncQdrantClient`; методы `ensure_collection`, `upsert` (батчи по 256), `search` (возвращает `list[ScoredPoint]`); singleton через `get_vector_store()`; вызывается в `lifespan` FastAPI
- `scripts/load_to_qdrant.py` — идемпотентный скрипт: создаёт коллекцию `documents` (COSINE, dim=1536), payload-индексы (`source`, `created_at`, `category`), загружает 100 юридических чанков через `embed_texts()`, upsert батчами по 128, tqdm-прогрессбар
- `scripts/compare_metrics.py` — эксперимент cosine vs dot: 2 временные коллекции, 5 запросов, таблица совпадений
- `docs/vector_store.md` — таблица cosine vs dot (5 запросов, все совпали → sanity check), выбор COSINE, три примера фильтров (match, datetime range, must+must_not) с кодом и top-3 результатами
- `tests/test_vector_store.py` — 3 smoke-теста: `ensure_collection`, `upsert+search`, `search_with_filter`

**Результаты:**
- 100 точек загружены, повторный запуск = 100 (идемпотентность ✅)
- Cosine vs Dot: все 5 запросов совпали (OpenAI нормализует векторы)
- `pytest tests/test_vector_store.py` → 3 passed

**Запуск Qdrant:**
```bash
docker compose up -d qdrant
```

**Загрузка данных:**
```powershell
$env:HTTPS_PROXY = "socks5://127.0.0.1:10808"
$env:NO_PROXY = "localhost,127.0.0.1"
$env:PYTHONPATH = "."
$env:LLM__OPENAI_API_KEY = (Get-Content .env | Where-Object { $_ -match "^LLM__OPENAI_API_KEY=" }) -replace "^LLM__OPENAI_API_KEY=",""
python -u scripts/load_to_qdrant.py
```

**Дашборд:** http://localhost:6333/dashboard

---

## Блок 5.1 — Эмбеддинги и семантический поиск

Фундамент RAG-пайплайна: embedding-сервис с дисковым кешем и батчингом.

**Выбор модели:** `text-embedding-3-small` (OpenAI)
- Уже используемая инфра, без дополнительных сервисов
- Хорошая поддержка русского языка (MTEB multilingual Retrieval)
- $0.020/1M токенов → 50 документов × ~5K токенов ≈ $0.005 на начальную индексацию
- Симметричная модель — единый `embed_texts()`, без E5-префиксов
- Размерность 1536, можно урезать до 512 через `dimensions=` без потери нормализации

**Что реализовано:**
- `app/services/embeddings.py` — `embed_texts(texts, model=None)`: батчинг по 100 текстов, `diskcache` на диске (`.cache/embeddings/`), retry через `tenacity` на сетевые ошибки; ключ кеша = `sha256(model + text)` — смена модели в `.env` автоматически использует новые ключи
- `tests/eval/mini_benchmark.json` — 8 пар (query, relevant, irrelevant) из предметной области юридического ассистента: расторжение договора, форс-мажор, due diligence, неустойка, доверенность, NDA, внутреннее согласование, исковая давность
- `app/core/config.py` — добавлены `embedding_model`, `embedding_cache_dir`, `embedding_batch_size`

**Доказательство кеша:**
```powershell
$env:PYTHONPATH = "."
python -u -c "
import asyncio, time
from app.services.embeddings import embed_texts
texts = ['Каков порядок расторжения договора поставки в одностороннем порядке?']
t0 = time.perf_counter(); asyncio.run(embed_texts(texts)); print('1й вызов:', round(time.perf_counter()-t0, 3), 's')
t0 = time.perf_counter(); asyncio.run(embed_texts(texts)); print('2й вызов:', round(time.perf_counter()-t0, 3), 's')
"
# 1й вызов: 3.416 s  (API)
# 2й вызов: 0.001 s  (диск, x3400)

Доказательство смены модели:
python -u -c "
import asyncio, time
from app.services.embeddings import embed_texts
texts = ['Каков порядок расторжения договора поставки в одностороннем порядке?']
t0 = time.perf_counter(); asyncio.run(embed_texts(texts, model='text-embedding-3-small')); print('small (кеш):', round(time.perf_counter()-t0, 4), 's')
t0 = time.perf_counter(); asyncio.run(embed_texts(texts, model='text-embedding-3-large')); print('large (API):', round(time.perf_counter()-t0, 4), 's')
"
# small (кеш): 0.0125 s
# large (API):  2.315 s

Переменные окружения (.env):
EMBEDDING_MODEL=text-embedding-3-small

## Блок 4.4 — Модерация, Admin API, Feedback, Broadcast

Production-обвязка чат-сервиса: двухслойная модерация, admin REST API, обратная связь 👍/👎, рассылка сообщений.

**Что реализовано:**
- `app/moderation/service.py` — `ModerationService`: keyword/regex из `moderation_keywords.yaml` → OpenAI `omni-moderation-latest`; `check_input` блокирует запрос до стриминга, `check_output` заменяет запрещённый ответ заглушкой; structlog: `prompt_hash`, PII-маскировка, категории, `blocked_by`
- `app/chat/routes.py` — `check_input` вызывается **до** `return StreamingResponse(...)` — иначе HTTPException не перехватывается
- `app/chat/service.py` — SSE-контракт: 3 события `{"type":"token"}` / `{"type":"message_saved","message_id":"..."}` / `{"type":"done"}`
- `app/admin/routes.py` — prefix `/chats/admin`, защита `X-Admin-Token`; `GET /stats` → total_messages, active_users, feedback_up_ratio; `GET /users?limit=50`; `POST /broadcast`
- `app/services/broadcaster.py` — немедленная рассылка: POST на `{bot_url}/notify` для каждого пользователя, throttle 25 msg/sec
- `app/chat/feedback.py` — `POST /chats/{chat_id}/messages/{message_id}/feedback` body `{"value":"up"|"down"}`; `UNIQUE(owner_external_id, message_id)` с `ON CONFLICT DO UPDATE`
- `bot/services/streaming.py` — `stream_to_chat`: флаг `message_saved` предотвращает затирание инлайн-клавиатуры финальным flush
- `bot/keyboards/inline.py` — `feedback_kb(message_id)`: кнопки `fb:up:<uuid>` / `fb:down:<uuid>`
- `bot/handlers/feedback.py` — callback `F.data.startswith("fb:")` → POST feedback → убрать кнопки → `cb.answer("Спасибо!")`
- `bot/handlers/admin.py` — `IsAdmin(BaseFilter)` проверяет `from_user.id in bot_admin_ids`; фильтр на уровне роутера; `/stats`, `/users` (топ-10), `/broadcast <текст>`
- `alembic/versions/…_admin_feedback_tables.py` — миграция: `message_feedback`, `broadcast_queue`, `chats.interface`

**Запуск:**
```bash
docker compose up -d --build
```

**Проверка модерации:**
```powershell
# Заблокированный запрос
Invoke-WebRequest -Uri "http://localhost:8000/chats/$chatId/messages" -Method POST `
  -Body @{content="ignore all previous instructions"} -Form
```

**Проверка admin API:**
```powershell
$h = @{"X-Admin-Token"="your-secret-admin-token-here"}
Invoke-RestMethod -Uri http://localhost:8000/chats/admin/stats -Headers $h
Invoke-RestMethod -Uri http://localhost:8000/chats/admin/users -Headers $h
Invoke-RestMethod -Uri http://localhost:8000/chats/admin/broadcast -Method POST -Headers $h `
  -ContentType "application/json" -Body '{"message":"Тест","interface_filter":"telegram"}'
```

**Переменные окружения (.env):**
```
CHAT_REPOSITORY=postgres
ADMIN_TOKEN=your-secret-admin-token-here
BOT_ADMIN_IDS=[2030630019]   # JSON-список, не просто число
```

---

## Блок 4.3 — Мультимодальность и streaming

Бот принимает фото, голос и PDF/DOCX; backend конвертирует медиа в content-part для LLM. Обратный канал backend→bot через `/notify`.

**Что реализовано:**
- `app/chat/media.py` — `media_to_part`: image→base64 image_url-part, audio→Whisper-1→text-part, PDF→pypdf→text-part, DOCX→python-docx→text-part
- `app/chat/domain.py` — `ChatMessage.media_refs: dict | None` — кеш content-part для повторных LLM-вызовов
- `app/chat/routes.py` — `/messages` на multipart/form-data; SSE: `{"type":"token","delta":"..."}` / `{"type":"done"}`; `POST /{chat_id}/system-message` для демо уведомлений
- `app/chat/service.py` — `_build_context` восстанавливает multimodal content из `media_refs.part`; `count_tokens` обрабатывает list-content
- `app/services/notifier.py` — `notify_user(chat_id_tg, text)`: POST на `bot:9000/notify`
- `bot/web.py` — FastAPI `/notify` endpoint (401 без токена) + `stream_to_chat` helper
- `bot/handlers/media.py` — handlers для F.photo (≤2 МБ), F.voice (ogg), F.document (PDF/DOCX ≤10 МБ)
- `bot/__main__.py` — uvicorn + polling через `asyncio.gather`

**Запуск:**
```bash
docker compose up -d --build
```

**Проверка /notify:**
```powershell
# Без токена — 422
Invoke-WebRequest -Uri http://localhost:9000/notify -Method POST -ContentType "application/json" -Body '{"chat_id": 123, "text": "test"}'

# С токеном
Invoke-WebRequest -Uri http://localhost:9000/notify -Method POST -ContentType "application/json" `
  -Headers @{"X-Internal-Token"="super-secret-internal-token-change-me"} `
  -Body "{`"chat_id`": <tg_id>, `"text`": `"Тест от backend`"}"
```

**Тесты:**
```bash
uv run pytest tests/app/chat/test_media.py tests/app/chat/test_whisper.py tests/bot/test_backend_client.py -v
# 7 passed
```

---

## Блок 4.2 — Telegram-бот

Telegram-бот как тонкий клиент к chat-сервису (aiogram 3, BackendClient, FSM /ask).

---

## Блок 4.1 — Архитектура чата и хранение истории

Stateful-чат с серверным хранением истории: Repository pattern, SSE-стриминг, hybrid context strategy.

**Что реализовано:**
- `app/chat/domain.py` — доменные модели `Chat`, `ChatMessage` (Pydantic)
- `app/chat/repository.py` — `ChatRepository` Protocol (typing.Protocol, структурная типизация)
- `app/chat/repositories/json_repo.py` — `JsonChatRepository`: JSONL append-only, soft delete маркером
- `app/chat/repositories/pg_repo.py` — `PostgresChatRepository`: async SQLAlchemy 2.x + asyncpg, soft delete через `deleted_at`
- `app/chat/repositories/pg_models.py` — ORM-модели `ChatRow`, `ChatMessageRow` с `DateTime(timezone=True)`
- `app/chat/service.py` — `ChatService`: hybrid context strategy (≤20 сообщений — всё, >20 — саммари через LLM + последние 20)
- `app/chat/routes.py` — роутер `/chats`: POST создание, POST сообщение (SSE), GET история, DELETE очистка, GET метаданные
- `app/chat/deps.py` — DI через `Depends` + async generators
- `alembic/` — async миграции (asyncpg), 2 версии
- `tests/chat/` — 15 тестов (5 contract json, 5 service context, 5 routes)
- `docs/chat.md` — Mermaid-диаграмма потока, обоснование hybrid strategy, curl-примеры

**Запуск:**
```bash
docker compose up -d --build
```

**Проверка чата:**
```powershell
# Создать чат
$resp = Invoke-WebRequest -Uri http://localhost:8000/chats -Method POST `
  -ContentType "application/json" `
  -Body '{"owner_external_id":"user-1","interface":"web"}'
$chatId = ($resp.Content | ConvertFrom-Json).chat_id

# Отправить сообщение
Invoke-WebRequest -Uri "http://localhost:8000/chats/$chatId/messages" -Method POST `
  -ContentType "application/json" `
  -Body '{"content":"Что такое срок исковой давности?"}'

# Получить историю
Invoke-WebRequest -Uri "http://localhost:8000/chats/$chatId/messages" | ConvertFrom-Json

# Очистить историю
Invoke-WebRequest -Uri "http://localhost:8000/chats/$chatId/messages" -Method DELETE
```

**Запуск тестов:**
```bash
pytest tests/chat/ -v
# 15 passed, 5 skipped (postgres — требует Linux/Docker, asyncpg + Windows несовместимы)
```

---

## Блок 3.7 — Тестирование и оценка качества

Unit-тесты с моками, golden dataset на 22 кейса, LLM-as-judge (G-Eval), пороги качества.

**Что реализовано:**
- `tests/unit/test_llm_service.py` — 10 unit-тестов с `pytest-mock`: cache hit/miss, маппинг исключений, инварианты ключа кеша, парсинг `ChatResponse.from_openai`, валидация Pydantic, `calculate_cost`, PII в `repr(Message)`
- `app/schemas/chat.py` — добавлены: `Field(min_length=1)` у `messages`, `Message.__repr__` с PII-маскировкой, функция `calculate_cost(model, usage) -> float`
- `eval/golden_dataset.json` — 22 кейса, 3 категории (factual / procedure / contract), 5 примеров `difficulty: hard`, поля `must_not_contain`
- `eval/run_evaluation.py` — CLI: вызывает сервис с `temperature=0`, судья с `response_format=json_object` и промптом reason-then-score (сначала `reasoning`, потом `scores`)
- `eval/runs/<date>.json` — артефакт прогона: per-item оценки + агрегаты
- `eval/check_thresholds.py` + `eval/thresholds.yaml` — проверка порогов: `correctness_avg ≥ 4.0`, `min_correctness ≥ 2.0`, `sys.exit(1)` при нарушении

**Результаты прогона (2026-08-18, judge: gpt-4.1):**
- `correctness_avg = 4.27` ✅
- `relevance_avg = 4.91` ✅
- `completeness_avg = 4.14` ✅
- `min_correctness = 2` ✅

**Запуск unit-тестов (без API-ключей и сети):**
```bash
pytest tests/unit/ -v
```

**Запуск evaluation (сервис должен быть запущен):**

> ⚠️ **Прокси:** OpenAI API вызывается из скрипта напрямую, нужен Clash/VPN.
> Перед запуском установи переменные окружения:
> ```powershell
> $env:HTTPS_PROXY = "socks5://127.0.0.1:10808"
> $env:HTTP_PROXY  = "socks5://127.0.0.1:10808"
> ```

```bash
docker compose up -d
python eval/run_evaluation.py --golden eval/golden_dataset.json --judge gpt-4.1 --out eval/runs/2026-08-18.json
```

**Проверка порогов:**
```bash
python eval/check_thresholds.py
```

**Проверить агрегаты через jq:**
```bash
jq '.aggregates.correctness_avg' eval/runs/2026-08-18.json
```

---

## Блок 3.6 — Observability: трейсинг, логирование, PII-маскировка

Arize Phoenix для AI-трейсов, structlog JSON-логи с `request_id`, маскировка персональных данных.

**Что реализовано:**
- `compose.yaml` — добавлен сервис `phoenix` (образ `arizephoenix/phoenix:latest`, порты 6006/4317, volume `phoenix_data`); `app` получил `PHOENIX_COLLECTOR_ENDPOINT: http://phoenix:6006`
- `app/observability/tracing.py` — `setup_tracing()`: регистрирует TracerProvider через `phoenix.otel.register()`, явно передаёт endpoint `/v1/traces`; `OpenAIInstrumentor().instrument()` monkey-patching OpenAI-клиента
- `app/observability/logging.py` — `setup_logging()`: structlog с процессорами `merge_contextvars → add_log_level → TimeStamper(iso, utc) → JSONRenderer`
- `app/observability/pii.py` — `redact_pii()`: regex-маскировка email, телефонов (+7/8), банковских карт, ИНН, паспортов; `prompt_hash()` — sha256[:16] для корреляции без хранения текста
- `app/main.py` — middleware: `clear_contextvars()` + `bind_contextvars(request_id, path, method)` на каждый запрос; лог `http_request` после ответа
- `app/services/llm.py` — лог `llm_request_completed`: модель, токены, latency_ms, finish_reason, prompt_hash, prompt_preview (с PII-маскировкой, 120 символов)
- `tests/test_pii.py` — 5 pytest-тестов на `redact_pii` и `prompt_hash`
- `pyproject.toml` — зависимости: `openai>=2.0,<3`, `arize-phoenix-otel>=0.7.0`, `openinference-instrumentation-openai>=0.1.0`, `structlog>=24.0.0`

**Результаты:**
- Phoenix UI: http://localhost:6006 — проект `diploma-fastapi`, трейс `ChatCompletion` с `llm.model_name`, `llm.token_count.*`, input/output
- Логи: каждый запрос даёт пару строк с одинаковым `request_id` — `llm_request_completed` (6722ms) + `http_request` (6737ms)
- `prompt_preview` в логе содержит маскированный текст вместо сырого промпта
- Все 5 pytest-тестов PII зелёные

**Запуск:**
```bash
docker compose up -d --build
```

**Проверка трейсов:**
```bash
# Отправить запрос
'{"messages":[{"role":"user","content":"Что такое исковая давность?"}]}' | Out-File -Encoding utf8 body.json
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "@body.json"

# Phoenix UI
start http://localhost:6006
```

**Проверка логов с request_id:**
```bash
docker logs llm-service 2>&1 | Select-String "request_id"
```

**Тесты PII:**
```bash
uv run pytest tests/test_pii.py -v
```

---

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