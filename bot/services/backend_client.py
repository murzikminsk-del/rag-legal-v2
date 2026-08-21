from typing import AsyncIterator
from uuid import UUID

import httpx


class BackendClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._chats: dict[str, UUID] = {}

    async def get_or_create_chat(self, owner_external_id: str, interface: str) -> UUID:
        if owner_external_id in self._chats:
            return self._chats[owner_external_id]
        r = await self._http.post(
            "/chats",
            json={"owner_external_id": owner_external_id, "interface": interface},
        )
        r.raise_for_status()
        chat_id = UUID(r.json()["chat_id"])
        self._chats[owner_external_id] = chat_id
        return chat_id

    async def send_message(
        self,
        chat_id: UUID,
        content: str,
        media: bytes | None = None,
        mime: str | None = None,
    ) -> AsyncIterator[str]:
        return self._stream_tokens(chat_id, content)

    async def _stream_tokens(self, chat_id: UUID, content: str) -> AsyncIterator[str]:
        async with self._http.stream(
            "POST",
            f"/chats/{chat_id}/messages",
            json={"content": content},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    token = line[6:]
                    if token == "[DONE]":
                        break
                    yield token

    async def clear_messages(self, chat_id: UUID) -> None:
        r = await self._http.delete(f"/chats/{chat_id}/messages")
        r.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()