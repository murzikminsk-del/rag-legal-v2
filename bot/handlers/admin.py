import httpx
from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from bot.config import settings
from bot.services.backend_client import BackendClient

router = Router()


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return (message.from_user is not None and
                message.from_user.id in settings.bot_admin_ids)


# Фильтр на уровне роутера — все хендлеры ниже автоматически защищены
router.message.filter(IsAdmin())


def _admin_headers() -> dict:
    return {"X-Admin-Token": settings.admin_token.get_secret_value()}


@router.message(Command("stats"))
async def cmd_stats(message: Message, backend: BackendClient) -> None:
    try:
        r = await backend._http.get("/chats/admin/stats", headers=_admin_headers())
        r.raise_for_status()
        d = r.json()
        ratio = d.get("feedback_up_ratio")
        ratio_str = f"{ratio:.0%}" if ratio is not None else "—"
        await message.answer(
            f"📊 <b>Статистика (24ч)</b>\n"
            f"Сообщений: {d['total_messages']}\n"
            f"Активных пользователей: {d['active_users']}\n"
            f"Рейтинг 👍: {ratio_str}",
            parse_mode="HTML",
        )
    except httpx.HTTPStatusError as e:
        await message.answer(f"Ошибка API: {e.response.status_code}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(Command("users"))
async def cmd_users(message: Message, backend: BackendClient) -> None:
    try:
        r = await backend._http.get("/chats/admin/users", headers=_admin_headers())
        r.raise_for_status()
        users = r.json()
        if not users:
            await message.answer("Пользователей нет.")
            return
        lines = [f"👤 {u['owner_external_id']} — {u.get('last_seen_at', '?')}" for u in users[:10]]
        await message.answer("Пользователи:\n" + "\n".join(lines))
    except httpx.HTTPStatusError as e:
        await message.answer(f"Ошибка API: {e.response.status_code}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, backend: BackendClient) -> None:
    text = message.text.removeprefix("/broadcast").strip()
    if not text:
        await message.answer("Использование: /broadcast <текст>")
        return
    try:
        r = await backend._http.post(
            "/chats/admin/broadcast",
            json={"message": text, "interface_filter": "telegram"},
            headers=_admin_headers(),
        )
        r.raise_for_status()
        result = r.json()
        sent = result.get("sent", "?")
        await message.answer(f"✅ Рассылка отправлена: {sent} получателей.")
    except httpx.HTTPStatusError as e:
        await message.answer(f"Ошибка API: {e.response.status_code}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")