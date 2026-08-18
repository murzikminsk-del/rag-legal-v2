#!/usr/bin/env python3
"""
CLI для оценки качества сервиса по golden dataset.

Запуск:
    python eval/run_evaluation.py \
        --golden eval/golden_dataset.json \
        --judge gpt-4.1 \
        --out eval/runs/2026-08-18.json \
        --app-url http://localhost:8000
"""
import os
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from openai import AsyncOpenAI

JUDGE_PROMPT = """\
You are a strict evaluator of an AI legal assistant.

Evaluate whether the Actual Answer correctly responds to the Question,
using the Expected Answer as a reference.

Question: {question}
Expected answer: {expected_answer}
Actual answer: {answer}

Return a JSON object. Fields MUST appear in this exact order:
1. "reasoning" — step-by-step analysis: is the answer relevant, accurate, complete? (2-5 sentences)
2. "scores" — object with integer scores from 1 (worst) to 5 (best):
   - "relevance": does the answer address the question?
   - "correctness": is the information factually accurate?
   - "completeness": are all important aspects covered?
3. "explanation" — one-line summary of the evaluation

Return ONLY the JSON object, no other text.\
"""


async def call_app(client: httpx.AsyncClient, base_url: str, question: str) -> str:
    payload = {
        "messages": [{"role": "user", "content": question}],
        "temperature": 0,
    }
    resp = await client.post(f"{base_url}/chat", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["content"]


async def call_judge(oai: AsyncOpenAI, judge_model: str,
                     question: str, expected: str, answer: str) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=question, expected_answer=expected, answer=answer
    )
    resp = await oai.chat.completions.create(
        model=judge_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


async def run(args: argparse.Namespace) -> None:
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    items = golden["items"]

    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    oai_http = httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
    oai = AsyncOpenAI(http_client=oai_http)
    out_items = []

    async with httpx.AsyncClient(trust_env=False) as http:
        for item in items:
            print(f"  {item['id']}...", end=" ", flush=True)
            try:
                answer = await call_app(http, args.app_url, item["question"])
                judgment = await call_judge(
                    oai, args.judge,
                    item["question"], item["expected_answer"], answer,
                )
                scores = judgment.get("scores", {})
                out_items.append({
                    "id": item["id"],
                    "question": item["question"],
                    "answer": answer,
                    "scores": {
                        "relevance":    scores.get("relevance", 1),
                        "correctness":  scores.get("correctness", 1),
                        "completeness": scores.get("completeness", 1),
                    },
                    "reasoning":   judgment.get("reasoning", ""),
                    "explanation": judgment.get("explanation", ""),
                })
                print(f"✓ correctness={scores.get('correctness', '?')}")
            except Exception as exc:
                print(f"✗ ERROR: {exc}", file=sys.stderr)
                out_items.append({
                    "id": item["id"],
                    "question": item["question"],
                    "answer": "",
                    "scores": {"relevance": 1, "correctness": 1, "completeness": 1},
                    "reasoning": f"ERROR: {exc}",
                    "explanation": "evaluation failed",
                })

    def avg(key: str) -> float:
        vals = [i["scores"][key] for i in out_items]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    result = {
        "run_id":           str(uuid.uuid4()),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "model_under_test": golden.get("model", "gpt-4.1-mini"),
        "judge_model":      args.judge,
        "golden_version":   golden.get("version", 1),
        "items": out_items,
        "aggregates": {
            "relevance_avg":    avg("relevance"),
            "correctness_avg":  avg("correctness"),
            "completeness_avg": avg("completeness"),
            "min_correctness":  min(i["scores"]["correctness"] for i in out_items),
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    agg = result["aggregates"]
    print(f"\nSaved → {out_path}")
    print(f"correctness_avg={agg['correctness_avg']}  "
          f"relevance_avg={agg['relevance_avg']}  "
          f"completeness_avg={agg['completeness_avg']}  "
          f"min_correctness={agg['min_correctness']}")


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="G-Eval evaluation runner")
    parser.add_argument("--golden",  default="eval/golden_dataset.json")
    parser.add_argument("--judge",   default="gpt-4.1")
    parser.add_argument("--out",     default=f"eval/runs/{today}.json")
    parser.add_argument("--app-url", default="http://localhost:8000")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()