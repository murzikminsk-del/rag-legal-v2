# Блок 6.4 — LangGraph: продвинутые паттерны

## 1. Выбор backend чекпоинтера

Выбран **SQLite** (`AGENT_CHECKPOINTER=sqlite`, файл `var/agent_checkpoints.sqlite`).

Мотивация: для разработки и тестирования SQLite не требует запущенного Postgres,
не нуждается в миграциях и работает без дополнительных контейнеров.
Переключение на Postgres меняет только одну переменную окружения — вся логика
агента остаётся неизменной.

| Backend  | Когда использовать                       |
|----------|------------------------------------------|
| memory   | unit-тесты, ephemeral-сессии             |
| sqlite   | локальная разработка, один процесс       |
| postgres | прод, несколько реплик FastAPI           |

---

## 2. Конфигурация Postgres в docker-compose

В `docker-compose.yml` для Postgres задаётся переменная окружения:
AGENT_CHECKPOINTER=postgres
DATABASE_URL=postgresql+asyncpg://app:secret@db:5432/rag_legal


URI преобразуется внутри `_psycopg_uri()`: psycopg v3 не поддерживает суффикс
`+asyncpg`, поэтому `postgresql+asyncpg://` заменяется на `postgresql://`.

После первого старта приложения `await saver.setup()` автоматически создаёт
служебные таблицы LangGraph. Проверить можно командой:

```sql
\dt
Ожидаемые таблицы: checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations.

В Alembic эти таблицы исключены через include_name — автогенерация миграций
их не затрагивает.

3. Опасный инструмент и Human-in-the-Loop
Опасный инструмент: send_email(to, subject, body)

Опасен, потому что отправляет письмо наружу — необратимое действие с реальными
последствиями. Ошибка адреса или случайная отправка недооформленного письма
не может быть отменена.

Схема до interrupt():

call_model — модель генерирует tool_call с именем send_email
execute_tool — пропускает вызов send_email (он идёт в HIL-ветку)
prepare_email — idempotent: только собирает payload из tool_call
в поле state.draft. Никаких side-effect.
Схема после interrupt():

confirm_and_send — вызывает interrupt({...}), граф останавливается.
Чекпоинтер сохраняет состояние. Клиент получает status="interrupted".
Клиент вызывает POST /agent/resume с Command(resume=True/False).
Граф возобновляется из сохранённого чекпоинта. Реальная отправка —
только здесь, только при approved=True.
Принцип идемпотентности: prepare_email можно повторить безопасно,
confirm_and_send с реальным вызовом выполняется ровно один раз, после явного
согласия человека.

4. Лог: __interrupt__ и возобновление
Вывод scripts/time_travel_demo.py:

1) INTERRUPT payload:
   {'type': 'approve_email', 'preview': {'to': 'client@example.com',
    'subject': 'Договор №42', 'body': 'Направляю договор на подпись.',
    'tool_call_id': 'call-1'}}

4) Две ветки:
   отказ      → sent=False
   одобрение  → sent=True, отправок=1

Итог: один и тот же вход дал две ветки —
      отказ (sent=False) и одобрение (sent=True).
Клиент при status="interrupted" получает поле interrupt с preview письма
и предлагает пользователю нажать «Подтвердить» или «Отменить». После этого
делается запрос /agent/resume с {"decision": true/false}.

5. Time travel
Вывод истории чекпоинтов для треда demo:

2) История чек-пойнтов (checkpoint_id / next):
   1f1b33ca-aab6-6e8c-8002-b17a4640748d  next=('confirm_and_send',)
   1f1b33ca-aab4-60dd-8001-ab844dfebf81  next=('prepare_email',)
   1f1b33ca-aab0-65fc-8000-e1b7c7ffbce1  next=('call_model',)
   1f1b33ca-aab0-65fb-bfff-8f9ece9143a3  next=('__start__',)

3) Прошлый чек-пойнт: sent=False, draft_готов=True, next=('confirm_and_send',)
Как работает time travel:

aget_state_history(config) возвращает все чекпоинты треда в обратном порядке.
По checkpoint_id можно загрузить любое прошлое состояние через
aget_state({"configurable": {"thread_id": ..., "checkpoint_id": ...}}).
«Перепроигрывание» — это новый тред с тем же началом, но другим решением
на interrupt. Это принципиально: возобновление существующего треда
детерминировано (нельзя «переголосовать»), а ветвление создаётся через
разные thread_id.
Демо показывает две ветки: тред demo (отказ) и тред demo-alt (одобрение)
при одинаковых входных данных.

6. Режим стриминга
Использован graph.astream(stream_mode=["updates", "messages"]).

Выбор обоснован:

"updates" даёт события по завершении каждого узла: клиент видит прогресс
(call_model → prepare_email → confirm_and_send) и получает
type="interrupt" ещё до окончания полного invoke.
"messages" добавляет потоковые токены от LLM — ответ начинает
появляться сразу, не ожидая полного завершения генерации.
Альтернатива astream_events мощнее, но избыточна: она генерирует десятки
событий на один вызов инструмента; для данного API достаточно двух режимов.

Пример SSE-ответа (curl через PowerShell):

data: {"type": "update", "nodes": ["call_model"]}
data: {"type": "update", "nodes": ["prepare_email"]}
data: {"type": "interrupt", "payload": {"type": "approve_email", "preview": {...}}}
data: {"type": "done"}
7. Политика прав (permission policy)
Поле user_role в configurable управляет HIL-гейтом:

Роль	Поведение
write-with-approve	interrupt() перед отправкой — требует ответа
full	interrupt() пропускается — отправка сразу
Одно поле — одно правило: пользователи с ролью full (например, системные
интеграции или суперадмины) получают сквозное выполнение без паузы.
Все остальные обязаны явно подтвердить опасное действие.

8. Что осталось хрупким / что улучшить
Проблема	Последствие	Улучшение
interrupt работает только с AsyncSqliteSaver / AsyncPostgresSaver; InMemorySaver теряет состояние при перезапуске	В тестах с memory-backend resume работает только в рамках одного процесса	Для прода всегда использовать Postgres
thread_id передаётся клиентом свободно	Любой клиент может читать чужой тред	Привязать thread_id к аутентифицированному пользователю
setup() вызывается при каждом старте приложения	Безвредно, но лишний запрос к БД	Добавить проверку через checkpoint_migrations
Нет очистки старых чекпоинтов	SQLite / Postgres будут расти бесконечно	Периодический DELETE чекпоинтов старше N дней
send_email_fn — заглушка (structlog)	В проде письма не отправляются	Подключить реальный SMTP / SendGrid
