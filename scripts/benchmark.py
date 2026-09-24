import asyncio
import time

from openai import OpenAI

from app.config import get_settings
from app.services.llm_client import AsyncLLMClient

PROMPTS = [f"Объясни одним абзацем концепцию №{i} из области права" for i in range(1, 21)]


def run_sync() -> float:
    import httpx2
    settings = get_settings()
    client = OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=30,
        http_client=httpx2.Client(trust_env=False),
    )
    start = time.perf_counter()
    for prompt in PROMPTS:
        client.chat.completions.create(
            model=settings.default_model,
            messages=[{"role": "user", "content": prompt}],
        )
    return time.perf_counter() - start


async def run_async(concurrency: int) -> float:
    client = AsyncLLMClient(concurrency=concurrency)
    start = time.perf_counter()
    results = await client.batch_chat(PROMPTS)
    elapsed = time.perf_counter() - start
    errors = sum(1 for r in results if isinstance(r, Exception))
    print(f"  concurrency={concurrency}: {elapsed:.2f}s  (errors={errors})")
    return elapsed


def main():
    print("=== Benchmark: sync vs async ===\n")

    print("Sync (sequential, 20 запросов):")
    sync_time = run_sync()
    print(f"  Total: {sync_time:.2f}s\n")

    print("Async batch_chat:")
    async_times: dict[int, float] = {}
    for c in [1, 5, 10]:
        async_times[c] = asyncio.run(run_async(c))

    print(f"\nSpeedup concurrency=10 vs sync: {sync_time / async_times[10]:.1f}x")


if __name__ == "__main__":
    main()