import re
from typing import Final

EMAIL_RE: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RU_RE: Final = re.compile(r"(?<!\w)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
PASSPORT_RU_RE: Final = re.compile(r"\b\d{4}\s?\d{6}\b")
INN_RE: Final = re.compile(r"\b\d{10}(?:\d{2})?\b")


def filter_output(answer: str, system_prompt: str, canary: str) -> str:
    if canary and canary in answer:
        raise ValueError("system_prompt leakage: canary detected")

    head = " ".join(system_prompt.split())[:80]
    if head and head.lower() in " ".join(answer.split()).lower():
        raise ValueError("system_prompt leakage: prefix detected")

    masked = EMAIL_RE.sub("[EMAIL]", answer)
    masked = PHONE_RU_RE.sub("[PHONE_RU]", masked)
    masked = PASSPORT_RU_RE.sub("[PASSPORT]", masked)
    masked = INN_RE.sub("[INN]", masked)
    return masked
