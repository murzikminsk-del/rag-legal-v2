import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml
from openai import AsyncOpenAI

from app.observability.pii import redact_pii, prompt_hash

log = structlog.get_logger()


@dataclass
class ModerationResult:
    allowed: bool
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    blocked_by: str = ""


class ModerationService:
    def __init__(
        self,
        llm: AsyncOpenAI,
        keywords_path: Path | None = None,
        use_openai: bool = True,
    ) -> None:
        self._llm = llm
        self._use_openai = use_openai
        self._patterns: list[tuple[str, re.Pattern]] = []
        if keywords_path and keywords_path.exists():
            self._load_keywords(keywords_path)

    def _load_keywords(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for category, patterns in (data or {}).items():
            for p in patterns:
                self._patterns.append((category, re.compile(p, re.IGNORECASE)))

    async def check_input(self, content: str) -> ModerationResult:
        result = self._check_keywords(content)
        if not result.allowed:
            log.warning(
                "moderation_input_blocked",
                hash=prompt_hash(content),
                preview=redact_pii(content[:120]),
                categories=result.categories,
                blocked_by=result.blocked_by,
            )
            return result

        if self._use_openai:
            result = await self._check_openai(content)
            if not result.allowed:
                log.warning(
                    "moderation_input_blocked",
                    hash=prompt_hash(content),
                    preview=redact_pii(content[:120]),
                    categories=result.categories,
                    blocked_by=result.blocked_by,
                )
        return result

    async def check_output(self, content: str) -> ModerationResult:
        result = self._check_keywords(content)
        if not result.allowed:
            log.warning(
                "moderation_output_blocked",
                hash=prompt_hash(content),
                categories=result.categories,
                blocked_by=result.blocked_by,
            )
        return result

    def _check_keywords(self, content: str) -> ModerationResult:
        categories: set[str] = set()
        reasons: list[str] = []
        for category, pattern in self._patterns:
            if pattern.search(content):
                categories.add(category)
                reasons.append(f"keyword:{category}")
        if categories:
            return ModerationResult(
                allowed=False,
                categories=list(categories),
                reasons=reasons,
                blocked_by="keyword",
            )
        return ModerationResult(allowed=True)

    async def _check_openai(self, content: str) -> ModerationResult:
        try:
            resp = await self._llm.moderations.create(
                model="omni-moderation-latest",
                input=content,
            )
            result = resp.results[0]
            if result.flagged:
                cats = [k for k, v in result.categories.__dict__.items() if v]
                return ModerationResult(
                    allowed=False,
                    categories=cats,
                    reasons=[f"openai:{c}" for c in cats],
                    blocked_by="openai_moderation",
                )
        except Exception:
            log.exception("openai_moderation_error")
        return ModerationResult(allowed=True)