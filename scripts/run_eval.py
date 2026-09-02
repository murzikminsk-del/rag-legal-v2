"""Прогон golden dataset через RAG и оценка метриками RAGAS 0.4.

Запуск:
    uv run --extra eval python scripts/run_eval.py --label baseline
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from openai import AsyncOpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LlamaIndexEmbeddingsWrapper
from ragas.llms import llm_factory
from ragas.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from llama_index.embeddings.openai import OpenAIEmbedding

from app.core.config import get_settings
from app.services.rag import RAGService


# ── Кастомная метрика (бинарная, без RAGAS-обёртки) ─────────────────────────

async def _has_citation_score(response: str, client: AsyncOpenAI) -> float:
    result = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": (
                "Содержит ли следующий ответ ссылку на источник?\n"
                "Ссылка — маркер вида '[1]', '[doc_id]', имя файла "
                "или фраза 'согласно …'.\n\n"
                f"Ответ: {response}\n\n"
                "Ответь строго одним словом: yes или no."
            ),
        }],
        max_tokens=5,
        temperature=0,
    )
    verdict = result.choices[0].message.content.strip().lower()
    return 1.0 if verdict.startswith("yes") else 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _score_row(metrics: dict, row: dict) -> dict:
    sample = SingleTurnSample(
        user_input=row["user_input"],
        response=row["response"],
        retrieved_contexts=row["retrieved_contexts"],
        reference=row.get("reference", ""),
    )
    results = await asyncio.gather(
        *[m.single_turn_ascore(sample) for m in metrics.values()],
        return_exceptions=True,
    )
    scores = {}
    for name, result in zip(metrics.keys(), results):
        if isinstance(result, Exception):
            print(f"    [{name}] ошибка: {result}")
            scores[name] = None
        else:
            scores[name] = result
    return scores


def _fmt(v) -> str:
    return f"{v:.3f}" if v is not None else "err"


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS eval runner")
    parser.add_argument("--golden", default="tests/eval/golden_dataset.json")
    parser.add_argument("--out", default="tests/eval/results")
    parser.add_argument("--label", default="baseline",
                        help="human-readable label: baseline / chunk_1024 / top_k_10")
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--embed-model", default="text-embedding-3-small")
    args = parser.parse_args()

    settings = get_settings()

    openai_client = AsyncOpenAI(api_key=settings.llm.openai_api_key.get_secret_value())

    # ── Judge LLM ────────────────────────────────────────────────────────────
    judge_llm = llm_factory(
        "gpt-4o-mini",
        provider="openai",
        client=openai_client,
    )

    # ── Judge embeddings ──────────────────────────────────────────────────────
    judge_emb = LlamaIndexEmbeddingsWrapper(
        OpenAIEmbedding(
            model=args.embed_model,
            api_key=settings.llm.openai_api_key.get_secret_value(),
        )
    )

    # ── Метрики ───────────────────────────────────────────────────────────────
    metrics: dict = {
        "faithfulness":      Faithfulness(llm=judge_llm),
        "answer_relevancy":  AnswerRelevancy(llm=judge_llm, embeddings=judge_emb),
        "context_precision": ContextPrecision(llm=judge_llm),
        "context_recall":    ContextRecall(llm=judge_llm),
    }

    # ── RAGService ────────────────────────────────────────────────────────────
    rag = RAGService()
    rag.build()

    # ── Golden dataset ────────────────────────────────────────────────────────
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    print(f"Загружено {len(golden)} пар. Judge: {args.judge_model}\n")

    rows: list[dict] = []
    for i, item in enumerate(golden):
        question = item["user_input"]
        reference = item.get("reference", "")
        print(f"[{i + 1:02d}/{len(golden)}] {question[:70]}…")

        result = await asyncio.to_thread(rag.evaluate_inputs, question)
        answer = result["answer"]
        retrieved_contexts = result["retrieved_contexts"]

        ragas_row = {
            "user_input": question,
            "response": answer,
            "retrieved_contexts": retrieved_contexts,
            "reference": reference,
        }

        scores, cit = await asyncio.gather(
            _score_row(metrics, ragas_row),
            _has_citation_score(answer, openai_client),
        )
        scores["has_citation"] = cit

        print(
            f"    faithfulness={_fmt(scores.get('faithfulness'))}"
            f"  ar={_fmt(scores.get('answer_relevancy'))}"
            f"  cp={_fmt(scores.get('context_precision'))}"
            f"  cr={_fmt(scores.get('context_recall'))}"
            f"  cit={_fmt(scores.get('has_citation'))}"
        )

        rows.append({
            "user_input": question,
            "response": answer,
            "reference": reference,
            **scores,
        })

    # ── Сохранение ────────────────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    metric_cols = [
        "faithfulness", "answer_relevancy",
        "context_precision", "context_recall", "has_citation",
    ]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"{timestamp}_{args.label}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")

    agg = {col: df[col].mean() for col in metric_cols if col in df.columns}
    agg_data = {
        "label": args.label,
        "timestamp": timestamp,
        **{k: round(v, 4) for k, v in agg.items()},
    }
    agg_path = out_dir / f"{timestamp}_{args.label}_agg.json"
    agg_path.write_text(json.dumps(agg_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"Агрегаты [{args.label}]:")
    for k, v in agg.items():
        print(f"  {k}: {v:.4f}")
    print(f"\nPer-row CSV : {csv_path}")
    print(f"Агрегаты JSON: {agg_path}")


if __name__ == "__main__":
    asyncio.run(main())