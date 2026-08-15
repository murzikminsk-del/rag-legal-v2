import jsonschema

from app.prompts.loader import load_text


# Читаем description из файла — не строка в коде, а загрузка из файла
# Это требование задания: description — тоже промпт, хранится отдельно
SEARCH_DOCS_DESCRIPTION = load_text("tools/search_docs")

# TOOLS — список инструментов, который передаётся модели при каждом запросе
# Это не сама функция — это её описание для модели
TOOLS = [
    {
        # type: function — говорим модели, что инструмент является функцией
        "type": "function",
        "function": {
            # name — имя функции, которое модель вернёт в tool_calls
            "name": "search_documents",

            # description — модель читает это, чтобы решить когда вызывать
            # Загружено из app/prompts/tools/search_docs.md
            "description": SEARCH_DOCS_DESCRIPTION,

            # strict: True — модель обязана вернуть ровно те поля, что в схеме
            "strict": True,

            # parameters — описание аргументов функции в формате JSON Schema
            "parameters": {
                # type: object — аргументы передаются как словарь
                "type": "object",

                "properties": {
                    "query": {
                        # Поисковый запрос — любая строка
                        "type": "string",
                        "description": "Поисковый запрос, например 'договор аренды' или 'неустойка'",
                    },
                    "doc_type": {
                        # Тип документа — только одно из четырёх значений
                        # enum ограничивает модель: она не может придумать свой тип
                        "type": "string",
                        "enum": ["contract", "policy", "claim", "charter", "any"],
                        "description": "Тип документа. Используй 'any' если тип не важен",
                    },
                },

                # Оба параметра обязательны — модель должна вернуть и query, и doc_type
                "required": ["query", "doc_type"],

                # additionalProperties: False — модель не может добавить лишние поля
                # Это обязательно при strict: True
                "additionalProperties": False,
            },
        },
    }
]

import jsonschema


def validate_arguments(tool_name: str, arguments: dict) -> None:
    # Находим нужный tool по имени
    tool = next(t for t in TOOLS if t["function"]["name"] == tool_name)

    # Берём JSON Schema параметров из описания инструмента
    schema = tool["function"]["parameters"]

    # jsonschema.validate проверяет: соответствуют ли аргументы схеме
    # Если нет — бросает jsonschema.ValidationError с описанием ошибки
    jsonschema.validate(instance=arguments, schema=schema)