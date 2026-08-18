import httpx
import time

URL = "http://localhost:8000/chat"
PAYLOAD = {
    "messages": [{"role": "user", "content": "Что такое исковая давность?"}],
    "model": "gpt-4.1-mini",
}

results = []
for i in range(1, 33):
    r = httpx.post(URL, json=PAYLOAD, timeout=30)
    results.append((i, r.status_code))
    print(f"Запрос {i:2d}: {r.status_code}")
    if r.status_code == 429:
        print(f"  Rate limit сработал на запросе {i} ✅")
        break

passed = any(status == 429 for _, status in results)
if not passed:
    print("❌ Rate limit не сработал за 32 запроса")
    raise SystemExit(1)