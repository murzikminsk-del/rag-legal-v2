import json
import logging
import httpx2

from openai import OpenAI

from app.config import get_settings
from app.prompts.loader import render_prompt
from app.tools.handlers import search_documents
from app.tools.schemas import TOOLS, validate_arguments

# Настраиваем логгер — будет писать в консоль с меткой времени
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Словарь: имя инструмента → функция-обработчик
# Когда модель вернёт tool_call с именем "search_documents" —
# мы найдём здесь нужную функцию и вызовем её
HANDLERS = {
    "search_documents": search_documents,
}


def run_tool_call(user_input: str) -> str:
    settings = get_settings()

    # Создаём клиента OpenAI — читает ключ из settings
    # .get_secret_value() — достаём строку из SecretStr
    client = OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.request_timeout,
        http_client=httpx2.Client(trust_env=False),
    )

    # Загружаем системный промпт из app/prompts/system_v1.j2
    # Подставляем переменную {{ company_name }} в шаблон
    system_prompt = render_prompt("system_v1", company_name="Юридический ассистент")

    # Начальная история диалога: системный промпт + вопрос пользователя
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    # Логируем входящий запрос
    logger.info("INPUT: %s", user_input)

    # ── ШАГ 1: первый запрос — модель решает нужен ли tool ──────────────────
    resp = client.chat.completions.create(
        model=settings.default_model,
        messages=messages,
        tools=TOOLS,
        # auto — модель сама решает: вызвать tool или ответить текстом
        tool_choice="auto",
    )

    # Достаём сообщение модели из первого варианта ответа
    msg = resp.choices[0].message

    # ВАЖНО: добавляем ход модели в историю
    # Если не добавить — второй запрос упадёт с ошибкой API
    messages.append(msg)

    # ── ШАГИ 2–3: если модель вызвала tool — выполняем и возвращаем результат
    if msg.tool_calls:
        for tc in msg.tool_calls:
            # Имя функции, которую попросила вызвать модель
            tool_name = tc.function.name

            # Аргументы приходят как JSON-строка — превращаем в словарь
            arguments = json.loads(tc.function.arguments)
            
            # Валидируем аргументы против JSON Schema — до вызова функции
            validate_arguments(tool_name, arguments)
            
            # Логируем: какой tool вызван и с какими аргументами
            logger.info("TOOL CALL: %s | args: %s", tool_name, arguments)

            # Находим функцию-обработчик по имени и вызываем её
            # **arguments — распаковывает словарь в именованные аргументы
            handler = HANDLERS[tool_name]
            result = handler(**arguments)

            # Логируем результат функции
            logger.info("TOOL RESULT: %s", result)

            # Добавляем результат в историю — роль "tool", привязка по id
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        # ── ШАГ 4: второй запрос — модель видит результат и пишет финальный ответ
        final = client.chat.completions.create(
            model=settings.default_model,
            messages=messages,
            tools=TOOLS,
        )

        answer = final.choices[0].message.content

        # Логируем финальный ответ и количество использованных токенов
        logger.info("FINAL ANSWER: %s", answer)
        logger.info("TOKENS: %s", final.usage.total_tokens)

        return answer

    # Если модель не вызвала tool — она сразу ответила текстом
    # Код не падает, просто возвращаем этот текст
    answer = msg.content
    logger.info("DIRECT ANSWER (no tool): %s", answer)
    logger.info("TOKENS: %s", resp.usage.total_tokens)

    return answer