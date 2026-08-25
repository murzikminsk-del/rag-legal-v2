import json
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
        files = {"media": ("file.bin", media, mime)} if media else None
        data = {"content": content}
        streaming_timeout = httpx.Timeout(connect=3.0, read=120.0, write=10.0, pool=5.0)
        try:
            async with self._http.stream(
                "POST",
                f"/chats/{chat_id}/messages",
                data=data,
                files=files,
                timeout=streaming_timeout,
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line.removeprefix("data: "))
                    if payload["type"] == "token":
                        yield payload["delta"]
                    elif payload["type"] == "done":
                        return
        except httpx.ConnectError:
            raise BackendError("Сервис недоступен, попробуйте позже")
        except httpx.ReadTimeout:
            raise BackendError("Ответ занимает слишком долго")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise BackendError("Слишком много запросов, подождите минуту")
            raise BackendError("Внутренняя ошибка сервиса")

    async def clear_messages(self, chat_id: UUID) -> None:
        r = await self._http.delete(f"/chats/{chat_id}/messages")
        r.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()


class BackendError(Exception):
    pass