from functools import lru_cache
from pathlib import Path

from jinja2 import Template

# Path(__file__) — путь к текущему файлу (loader.py)
# .parent — папка, в которой он лежит (app/prompts/)
PROMPTS_DIR = Path(__file__).parent


# lru_cache(maxsize=8) — кешируем до 8 промптов в памяти
# Без кеша файл читался бы заново при каждом запросе
@lru_cache(maxsize=8)
def render_prompt(name: str, **kwargs) -> str:
    # Собираем путь к файлу: app/prompts/system_v1.j2
    path = PROMPTS_DIR / f"{name}.j2"

    # Читаем текст файла в кодировке UTF-8
    text = path.read_text(encoding="utf-8")

    # Template(text) — создаём Jinja2-шаблон из текста
    # .render(**kwargs) — подставляем переменные, например {{ assistant_name }}
    return Template(text).render(**kwargs)


def load_text(name: str) -> str:
    # Читает обычный .md файл без шаблонизации
    # Используется для description у tool
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")