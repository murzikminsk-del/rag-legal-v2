# RAG — документация блока 5.5

## Архитектура

```mermaid
flowchart LR
    subgraph INGESTION["Контур индексации (offline)"]
        direction TB
        D[("data/\n30 .md файлов")]
        L["IngestionService\nload_file()"]
        S["SentenceSplitter\nchunk_size=512\nchunk_overlap=64"]
        E["OpenAIEmbedding\ntext-embedding-3-small"]
        Q[("Qdrant\nrag_legal_v2\n901 нод")]
        D --> L --> S --> E --> Q
    end

    subgraph QUERY["Контур запроса (online)"]
        direction TB
        U["Пользователь\n(Telegram бот)"]
        R["RAGService\nretrieve_context()"]
        RR["Cohere Rerank\nrerank-v3.5\ntop_n=5"]
        G["Score-guard\n< 0.3 → отказ"]
        C["ChatService\n_build_context()"]
        LLM["OpenAI\ngpt-4.1-mini"]
        A["Ответ с цитатами [1][2]"]
        U --> R --> RR --> G --> C --> LLM --> A
    end

    Q -.->|"similarity_top_k=10"| R
Параметры чанкинга
Параметр	Значение	Обоснование
chunk_size	512	Baseline из блока 5.3; достаточно для одного юридического пункта
chunk_overlap	64	~12% от chunk_size — сохраняет контекст на стыке чанков
Чанкер	SentenceSplitter	Разбивает по предложениям, не рвёт юридические конструкции посередине
Embed-модель	text-embedding-3-small	1536 измерений, метрика COSINE, оптимальное соотношение качества и стоимости
Коллекция rag_legal_v2: 30 документов → 901 нода.

Re-ranker
Cohere Rerank (rerank-v3.5, top_n=5).

Retriever возвращает top_k=10 кандидатов по косинусному сходству; реранкер пересортировывает их кросс-энкодером и оставляет 5 лучших. Это устраняет ложных «соседей» по embedding-пространству, которые семантически нерелевантны.

Реранкер опционален: если COHERE_API_KEY не задан — используются первые 5 кандидатов по dense-score.

Score-guard и threshold
Двухслойная защита от галлюцинаций
Слой	Механизм	Где реализован
Код	if top_score < 0.3 → возврат готового отказа, LLM не вызывается	app/services/rag.py → answer()
Промпт	«Если ответа в контексте нет — так и скажи»	system-сообщение в _build_context()
Выбор порогового значения
RAG_SCORE_THRESHOLD = 0.3 — для text-embedding-3-small + COSINE.

Обоснование:

Релевантные вопросы по корпусу: top_score = 0.47–0.87
Вопрос вне базы («Как приготовить борщ?»): top_score = 0.188
Граница 0.3 разделяет оба класса с запасом ≈ 0.27 до ближайшего релевантного
Формула калибровки:

threshold = min(score_relevant) − 0.5 × (min(score_relevant) − max(score_irrelevant))
           = 0.47 − 0.5 × (0.47 − 0.188) ≈ 0.33 → округлено до 0.3
На других embedding-моделях порог нужно перекалибровать по golden dataset.

Endpoints
Метод	URL	Описание
POST	/rag/query	Задать вопрос RAG напрямую; возвращает answer, top_score, confident, sources[]
POST	/rag/documents/upload	Загрузить документ (.md, .pdf, .docx, .html) для фоновой индексации; 202 Accepted
POST	/chats/{id}/messages	Основной chat-endpoint; RAG-контекст внедряется автоматически до вызова LLM
Зависимости
Пакет	Назначение
llama-index-core	IngestionPipeline, VectorStoreIndex, SentenceSplitter
llama-index-vector-stores-qdrant	Коннектор к Qdrant
llama-index-embeddings-openai	OpenAIEmbedding
llama-index-readers-file	PyMuPDFReader, DocxReader, HTMLTagReader, MarkdownReader
cohere	Rerank API
qdrant-client	Синхронный клиент для retrieval