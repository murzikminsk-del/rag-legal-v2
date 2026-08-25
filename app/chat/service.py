import tiktoken
from openai import AsyncOpenAI
from uuid import UUID
from typing import AsyncIterator

import structlog

from app.chat.domain import Chat, ChatMessage
from app.chat.repository import ChatRepository

log = structlog.get_logger()

CONTEXT_WINDOW = 128_000
RESPONSE_TOKENS = 4_096
SAFETY_MARGIN = 512
KEEP_RECENT = 20
SUMMARIZE_PROMPT = (
    "Сделай краткое саммари этого диалога. "
    "Явно перечисли: темы, имена, числа, решения, нерешённые вопросы. "
    "Отвечай на том же языке, что и диалог."
)


def _enc():
    return tiktoken.get_encoding("o200k_base")


def count_tokens(messages: list[dict]) -> int:
    enc = _enc()
    total = 2
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
        else:
            text = content or ""
        total += 4 + len(enc.encode(text))
    return total


def fit_to_budget(messages: list[dict], budget: int) -> list[dict]:
    system = [m for m in messages if m["role"] == "system"]
    non_system = [m for m in messages if m["role"] != "system"]
    while non_system and count_tokens(system + non_system) > budget:
        non_system.pop(0)
    return system + non_system

def _msg_to_dict(msg: ChatMessage) -> dict:
    if msg.role == "user" and msg.media_refs and msg.media_refs.get("part"):
        content = [
            {"type": "text", "text": msg.content},
            msg.media_refs["part"],
        ]
        return {"role": "user", "content": content}
    return {"role": msg.role, "content": msg.content}


class ChatService:
    def __init__(self, repository: ChatRepository, llm: AsyncOpenAI) -> None:
        self._repo = repository
        self._llm = llm

    async def create_chat(
        self,
        owner_external_id: str,
        interface: str,
        system_prompt: str | None = None,
    ) -> Chat:
        return await self._repo.create_chat(owner_external_id, interface, system_prompt)

    async def get_chat(self, chat_id: UUID) -> Chat | None:
        return await self._repo.get_chat(chat_id)

    async def send_message(
        self,
        chat_id: UUID,
        user_content: str,
        media_part: dict | None = None,
        media_meta: dict | None = None,
    ) -> AsyncIterator[str]:
        user_msg = ChatMessage(
            chat_id=chat_id,
            role="user",
            content=user_content,
            media_refs=media_meta,
        )
        await self._repo.append_message(chat_id, user_msg)

        chat = await self._repo.get_chat(chat_id)
        history = await self._repo.list_messages(chat_id, limit=200)

        messages = await self._build_context(chat, history, current_media_part=media_part)

        budget = CONTEXT_WINDOW - RESPONSE_TOKENS - SAFETY_MARGIN
        messages = fit_to_budget(messages, budget)

        collected = []
        try:
            stream = await self._llm.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    collected.append(delta)
                    yield delta
        except Exception:
            log.exception("stream_interrupted", chat_id=str(chat_id))
        finally:
            if collected:
                full_text = "".join(collected)
                assistant_msg = ChatMessage(
                    chat_id=chat_id, role="assistant", content=full_text
                )
                await self._repo.append_message(chat_id, assistant_msg)

    async def clear_history(self, chat_id: UUID) -> None:
        await self._repo.soft_delete_messages(chat_id)

    async def _build_context(
        self, chat: Chat | None, history: list[ChatMessage],
        current_media_part: dict | None = None,
    ) -> list[dict]:
        messages: list[dict] = []

        if chat and chat.system_prompt:
            messages.append({"role": "system", "content": chat.system_prompt})

        if len(history) <= KEEP_RECENT:
            for msg in history:
                messages.append(_msg_to_dict(msg))
            return messages

        old = history[:-KEEP_RECENT]
        recent = history[-KEEP_RECENT:]

        old_text = "\n".join(f"{m.role}: {m.content}" for m in old)
        summary_resp = await self._llm.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": old_text},
            ],
        )
        summary = summary_resp.choices[0].message.content or ""

        messages.append({"role": "system", "content": f"[Саммари предыдущего диалога]\n{summary}"})
        for msg in recent:
            messages.append(_msg_to_dict(msg))

        return messages