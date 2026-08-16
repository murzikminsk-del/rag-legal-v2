from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    name: str
    input_price_per_1m: float
    output_price_per_1m: float
    max_tokens: int
    description: str


AVAILABLE_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="gpt-4.1-mini",
        name="GPT-4.1 Mini",
        input_price_per_1m=0.40,
        output_price_per_1m=1.60,
        max_tokens=16000,
        description="Быстрая и экономичная модель для большинства задач",
    ),
    ModelInfo(
        id="gpt-4.1",
        name="GPT-4.1",
        input_price_per_1m=2.00,
        output_price_per_1m=8.00,
        max_tokens=16000,
        description="Мощная модель для сложных юридических документов",
    ),
    ModelInfo(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        input_price_per_1m=0.15,
        output_price_per_1m=0.60,
        max_tokens=16000,
        description="Самая быстрая и дешёвая модель для простых запросов",
    ),
]