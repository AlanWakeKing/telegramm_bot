from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import html

from ..services import repo

router = Router()


def format_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def is_supported_button_url(link: str) -> bool:
    return link.startswith("https://") or link.startswith("http://") or link.startswith("tg://")


def build_link_kb(link: str | None) -> InlineKeyboardMarkup | None:
    if not link or not is_supported_button_url(link):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть", url=link)]])


@router.message(F.text == "📱 Конфигурация")
async def my_config(message: Message, session: AsyncSession):
    user = await repo.load_user_with_session(session, message.from_user.id)
    if not user:
        await message.answer("Сессия не найдена. Нажми /start")
        return

    profiles = await repo.list_active_profiles(session, user["user_id"])
    if not profiles:
        await message.answer("У вас пока нет активных ключей. Оформите покупку в 🛒 Купить VPN")
        return

    parts: list[str] = []
    for p in profiles:
        server_name = p.get("server_name") or str(p["server_id"])
        created = format_dt(p.get("created_at"))
        access_until = format_dt(p.get("access_until"))
        key_name = f"{p['protocol']}_{server_name}"
        header = (
            f"🔑 Ключ: {key_name}\n"
            f"Протокол: {p['protocol']}\n"
            f"Сервер: {server_name}\n"
            f"Создан: {created}\n"
            f"Действует до: {access_until}"
        )

        config_uri = p.get("config_uri")
        if config_uri and "://" not in config_uri:
            config_uri = f"{p['protocol']}://{config_uri}"

        if config_uri:
            safe_uri = html.escape(config_uri)
            text = f"{header}\n\nКонфигурация:\n<code>{safe_uri}</code>\n\nСкопируйте и откройте в приложении."
        else:
            text = f"{header}\n\nКонфигурация еще не готова. Обратитесь в поддержку."
        parts.append(text)

    full_text = "\n\n──────────\n\n".join(parts)

    # Telegram limit ~4096 chars; chunk if needed
    if len(full_text) <= 3900:
        await message.answer(full_text)
        return

    chunk = ""
    for part in parts:
        candidate = f"{chunk}\n\n──────────\n\n{part}" if chunk else part
        if len(candidate) > 3900:
            await message.answer(chunk)
            chunk = part
        else:
            chunk = candidate
    if chunk:
        await message.answer(chunk)
