from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from aiogram import Bot
from aiogram.types import Message
from typing import AsyncIterator


class NotifyRequest(BaseModel):
    chat_id: int
    text: str


def build_notify_api(bot: Bot, internal_token: str) -> FastAPI:
    api = FastAPI()

    @api.post("/notify")
    async def notify(
        req: NotifyRequest,
        x_internal_token: str = Header(...),
    ) -> dict:
        if x_internal_token != internal_token:
            raise HTTPException(status_code=401)
        await bot.send_message(chat_id=req.chat_id, text=req.text)
        return {"ok": True}

    return api


async def stream_to_chat(message: Message, tokens: AsyncIterator[str]) -> str:
    buffer = ""
    sent = None
    async for delta in tokens:
        buffer += delta
        if sent is None:
            sent = await message.answer(buffer)
        else:
            try:
                await sent.edit_text(buffer)
            except Exception:
                pass
    if sent and buffer:
        try:
            await sent.edit_text(buffer)
        except Exception:
            pass
    return buffer