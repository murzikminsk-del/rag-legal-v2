from __future__ import annotations

from openai.types.chat import ChatCompletion
from pydantic import BaseModel, Field

from app.observability.pii import redact_pii

# цена за 1M токенов (input, output) в USD
_PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1":      (2.00, 8.00),
    "gpt-4o":       (5.00, 15.00),
    "gpt-4o-mini":  (0.15, 0.60),
}


class Message(BaseModel):
    role: str
    content: str = Field(max_length=32_000)

    def __repr__(self) -> str:
        return f"Message(role={self.role!r}, content={redact_pii(self.content)!r})"


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def calculate_cost(model: str, usage: Usage) -> float:
    """Возвращает стоимость запроса в USD по публичному прайсу OpenAI."""
    input_price, output_price = _PRICE_PER_1M.get(model, (2.00, 8.00))
    return (usage.prompt_tokens * input_price + usage.completion_tokens * output_price) / 1_000_000


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    model: str = "gpt-4.1-mini"
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=16000)
    user_id: str | None = None
    session_id: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "messages": [{"role": "user", "content": "Что такое исковая давность?"}],
                    "model": "gpt-4.1-mini",
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
                {
                    "messages": [
                        {"role": "system", "content": "Ты юридический ассистент."},
                        {"role": "user", "content": "Объясни статью 395 ГК РФ."},
                    ],
                    "model": "gpt-4.1-mini",
                    "temperature": 0.3,
                    "max_tokens": 1024,
                    "session_id": "sess-001",
                },
            ]
        }
    }


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: Usage
    finish_reason: str
    cached: bool = False

    @classmethod
    def from_openai(cls, completion: ChatCompletion, cached: bool = False) -> ChatResponse:
        choice = completion.choices[0]
        return cls(
            content=choice.message.content or "",
            model=completion.model,
            usage=Usage(
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                total_tokens=completion.usage.total_tokens,
            ),
            finish_reason=choice.finish_reason or "stop",
            cached=cached,
        )


class ChatDelta(BaseModel):
    content: str | None = None
    usage: Usage | None = None