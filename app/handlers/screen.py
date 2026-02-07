from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo


def _build_kwargs(text: str, reply_markup, parse_mode, disable_web_page_preview):
    kwargs = {"text": text, "reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if disable_web_page_preview is not None:
        kwargs["disable_web_page_preview"] = disable_web_page_preview
    return kwargs


async def _try_edit(bot, chat_id: int, message_id: int, text: str, reply_markup, parse_mode, disable_web_page_preview) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            **_build_kwargs(text, reply_markup, parse_mode, disable_web_page_preview),
        )
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return True
    except Exception:
        pass
    return False


async def edit_screen(
    message: Message,
    session: AsyncSession,
    text: str,
    reply_markup=None,
    tg_user_id: int | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> int:
    user_id = tg_user_id or message.from_user.id
    user = await repo.load_user_with_session(session, user_id)
    state = (user or {}).get("state") or "menu"
    ui = ((user or {}).get("payload") or {}).get("ui") or {}
    stored_id = ui.get("screen_message_id")

    candidate_ids = []
    if stored_id:
        candidate_ids.append(int(stored_id))
    if message.from_user and message.from_user.is_bot:
        if message.message_id not in candidate_ids:
            candidate_ids.append(message.message_id)

    for candidate_id in candidate_ids:
        if await _try_edit(message.bot, message.chat.id, candidate_id, text, reply_markup, parse_mode, disable_web_page_preview):
            if stored_id != candidate_id and user:
                await repo.set_state_payload(session, user_id, state, "ui", {"screen_message_id": candidate_id})
                await session.commit()
            return candidate_id

    sent = await message.answer(**_build_kwargs(text, reply_markup, parse_mode, disable_web_page_preview))
    if user:
        await repo.set_state_payload(session, user_id, state, "ui", {"screen_message_id": sent.message_id})
        await session.commit()
    return sent.message_id


async def edit_screen_by_user(
    bot,
    chat_id: int,
    session: AsyncSession,
    tg_user_id: int,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> int:
    user = await repo.load_user_with_session(session, tg_user_id)
    state = (user or {}).get("state") or "menu"
    ui = ((user or {}).get("payload") or {}).get("ui") or {}
    stored_id = ui.get("screen_message_id")

    if stored_id:
        if await _try_edit(bot, chat_id, int(stored_id), text, reply_markup, parse_mode, disable_web_page_preview):
            return int(stored_id)

    sent = await bot.send_message(chat_id, **_build_kwargs(text, reply_markup, parse_mode, disable_web_page_preview))
    if user:
        await repo.set_state_payload(session, tg_user_id, state, "ui", {"screen_message_id": sent.message_id})
        await session.commit()
    return sent.message_id
