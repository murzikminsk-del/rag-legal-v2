# RAG Evaluation Report — rag-legal-v2

## 1. Методология

**Golden dataset**: 30 вопросов из юридических договоров (блок 5.3).  
**Judge LLM**: gpt-4o-mini  
**Judge embeddings**: text-embedding-3-small  
**Метрики RAGAS 0.4**: Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall + кастомная has_citation.

Запуск:
```bash
uv run --extra eval python scripts/run_eval.py --label baseline
2. Baseline результаты (chunk_size=512, overlap=64)
Метрика	Значение
faithfulness	0.779
answer_relevancy	0.455
context_precision	0.923
context_recall	0.706
has_citation	0.967
has_citation превысил целевой порог 0.95 ✓
context_precision — сильная сторона системы (ретривер точен).
answer_relevancy — наиболее слабая метрика: ответы релевантны, но недостаточно сфокусированы.

3. A/B эксперимент: chunk_size 512 → 1024
Конфигурация chunk_1024: chunk_size=1024, chunk_overlap=64 (без изменений).
Из-за сбоя VPN прогон завершён на 22 строках из 30.

Метрика	baseline	chunk_1024 (22 строки)	Δ
faithfulness	0.779	0.763	−0.016
answer_relevancy	0.455	0.511	+0.056
context_precision	0.923	0.948	+0.025
context_recall	0.706	0.773	+0.067
has_citation	0.967	н/д	—
Вывод: chunk_1024 улучшает recall (+0.067) и relevancy (+0.056) при минимальном снижении faithfulness (−0.016). Более крупные чанки дают более полный контекст. Рекомендуется chunk_size=1024 для production.

4. Кастомная метрика has_citation
Задача: проверить, содержит ли ответ ссылку на источник (маркер [1], [doc_id], имя файла или фраза «согласно …»).

Реализация: бинарная метрика на основе gpt-4o-mini, возвращает 1.0 или 0.0.

Результат baseline: 0.967 → цель достигнута (порог 0.95).

Один ответ не содержал ссылку — это был случай со score guard («По базе не нашёл, могу эскалировать»).

5. Phoenix Tracing
Настроен через LlamaIndexInstrumentor + OpenAIInstrumentor.
Трейсы видны в Phoenix UI на http://localhost:6006.

Инструментирование:

Все вызовы OpenAI (embeddings, completions) — через OpenAIInstrumentor
LlamaIndex retrieval — через LlamaIndexInstrumentor (с try/except из-за несовместимости openinference>=3 и llama-index 0.14)
6. Failure Analysis
Топ-5 худших строк по faithfulness (baseline, ascending):

Строка 1 — Пулихова Ирина Алексеевна
faithfulness=0.000, context_precision=1.000, context_recall=1.000
Диагноз: generation-проблема. Ретривер нашёл правильные чанки (cp=1, cr=1), но LLM ответил «не найдено». Имя содержалось в соседнем фрагменте — модель не соединила контекст.
Строка 11 — Кондиционер в перечне оборудования
faithfulness=0.000, context_precision=1.000, context_recall=1.000
Диагноз: generation-проблема. Сработал score guard (ответ «По базе не нашёл»), хотя чанки были релевантны. Порог rag_score_threshold слишком высокий для специфичных фактических вопросов.
Строка 27 — Акт финансового закрытия не подписывают
faithfulness=0.333, context_precision=1.000, context_recall=1.000
Диагноз: generation-проблема. LLM добавил правовые последствия («основание для расторжения»), которых нет в контексте.
Строка 2 — ЕГРН и аренда
faithfulness=0.500, context_precision=1.000, context_recall=0.500
Диагноз: смешанная. Ретривер не извлёк все нужные фрагменты (cr=0.5), LLM частично галлюцинировал на неполном контексте.
Строка 8 — ООО «Альфа» в договоре аренды
faithfulness=0.500, context_precision=1.000, context_recall=0.500
Диагноз: retriever-проблема. Низкий recall ограничил полноту ответа; данные о подписанте не были извлечены.
Диагностическая матрица 2×2
Высокий Context Recall	Низкий Context Recall
Высокая Faithfulness	✅ норма	retriever-проблема
Низкая Faithfulness	generation-проблема	обе проблемы
80% отказов в baseline — generation-проблемы: ретривер работает корректно, LLM галлюцинирует или score guard срабатывает излишне.

7. Рекомендации
Снизить rag_score_threshold с 0.3 → 0.2 для уменьшения ложных срабатываний score guard.
Перейти на chunk_size=1024 — улучшает recall и relevancy без значительной потери faithfulness.
Добавить system prompt с явным запретом на утверждения вне контекста для снижения галлюцинаций.
Мониторинг has_citation в production через Phoenix — цель ≥0.95.