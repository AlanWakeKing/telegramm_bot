from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo

router = Router()


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Реферальная ссылка", callback_data="profile:ref")],
        [InlineKeyboardButton(text="История оплат", callback_data="profile:payments"),
         InlineKeyboardButton(text="Уведомления", callback_data="profile:notify")],
        [InlineKeyboardButton(text="Активные ключи", callback_data="profile:keys")],
    ])


def payments_kb(index: int, total: int, has_file: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬅️", callback_data="payhist:prev"),
            InlineKeyboardButton(text=f"{index}/{total}", callback_data="payhist:noop"),
            InlineKeyboardButton(text="➡️", callback_data="payhist:next"),
        ]
    ]
    if has_file:
        rows.append([InlineKeyboardButton(text="📎 Открыть чек", callback_data="payhist:file")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="payhist:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_payment(p: dict, idx: int, total: int) -> str:
    amount = p.get("amount_minor")
    currency = p.get("currency") or "RUB"
    status = (p.get("status") or "-").upper()
    date = format_dt(p.get("updated_at"))
    kind = (p.get("meta") or {}).get("type") or "оплата"
    file_flag = "есть" if p.get("tg_file_id") else "нет"
    return (
        f"Найдено: {total}\n\n"
        f"Оплата #{p['id']}\n"
        f"Сумма: {amount} {currency}\n"
        f"Статус: {status}\n"
        f"Дата: {date}\n"
        f"Тип: {kind}\n"
        f"Файл: {file_flag}"
    )


def format_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def build_profile_text(user: dict, profiles: list[dict], balance: int, settings: dict) -> str:
    active_count = len(profiles)
    now = datetime.now(timezone.utc)
    access_until_values = [p.get("access_until") for p in profiles if p.get("access_until")]
    nearest_until = max(access_until_values) if access_until_values else None

    if active_count == 0:
        sub_status = "нет"
    else:
        if nearest_until and isinstance(nearest_until, datetime) and nearest_until >= now:
            sub_status = "активен"
        elif nearest_until:
            sub_status = "истёк"
        else:
            sub_status = "активен"

    notifications = "включены" if settings.get("notifications_enabled") else "выключены"
    language = settings.get("language") or "ru"

    return (
        f"👤 Профиль\n\n"
        f"ID: {user['tg_user_id']}\n"
        f"Username: @{user.get('username') or '-'}\n\n"
        f"Статус подписки: {sub_status}\n"
        f"Действует до: {format_dt(nearest_until)}\n"
        f"Баланс: {balance} ₽\n"
        f"Активных ключей: {active_count}\n\n"
        f"Уведомления: {notifications}\n"
        f"Язык: {language}"
    )


async def render_screen(message: Message, session: AsyncSession, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    user = await repo.load_user_with_session(session, message.from_user.id)
    msg_id = None
    if user:
        ui = (user.get("payload") or {}).get("ui") or {}
        msg_id = ui.get("screen_message_id")
    try:
        if msg_id:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
    except Exception:
        pass
    sent = await message.answer(text, reply_markup=reply_markup)
    await repo.set_state_payload(session, message.from_user.id, "profile", "ui", {"screen_message_id": sent.message_id})
    await session.commit()


@router.message(F.text == "👤 Профиль")
async def profile(message: Message, session: AsyncSession):
    user = await repo.load_user_with_session(session, message.from_user.id)
    if not user:
        await message.answer("Сессия не найдена. Нажми /start")
        return

    profiles = await repo.list_active_profiles(session, user["user_id"])
    balance = await repo.get_balance(session, user["user_id"])
    settings = await repo.get_user_settings(session, user["user_id"])
    text = build_profile_text(user, profiles, balance, settings)
    await repo.set_state_clear(session, message.from_user.id, "profile")
    await session.commit()
    await render_screen(message, session, text, reply_markup=profile_kb())


@router.callback_query(F.data.startswith("profile:"))
async def profile_callbacks(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer("Нет сессии", show_alert=True)
        return

    action = call.data.split(":")[1]

    if action == "ref":
        me = await bot.get_me()
        ref_code = user.get("referral_code") or f"REF{user['user_id']}"
        ref_link = f"https://t.me/{me.username}?start=ref{ref_code}"
        await call.message.edit_text(f"Ваша реферальная ссылка:\n{ref_link}", reply_markup=profile_kb())
        await call.answer()
        return

    if action == "payments":
        history = await repo.load_payment_history(session, user["user_id"], limit=10)
        if not history:
            await call.message.edit_text("История оплат пуста.", reply_markup=profile_kb())
            await call.answer()
            return
        await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": 0})
        await session.commit()
        total = len(history)
        text = format_payment(history[0], 1, total)
        await call.message.edit_text(text, reply_markup=payments_kb(1, total, bool(history[0].get("tg_file_id"))))
        await call.answer()
        return

    if action == "notify":
        settings = await repo.get_user_settings(session, user["user_id"])
        enabled = not bool(settings.get("notifications_enabled"))
        await repo.set_notifications(session, user["user_id"], enabled)
        await session.commit()
        profiles = await repo.list_active_profiles(session, user["user_id"])
        balance = await repo.get_balance(session, user["user_id"])
        settings = await repo.get_user_settings(session, user["user_id"])
        text = build_profile_text(user, profiles, balance, settings)
        if enabled:
            text = f"{text}\n\n✅ Уведомления включены."
        else:
            text = f"{text}\n\n⚠️ Уведомления выключены. Важные сообщения могут быть пропущены."
        await call.message.edit_text(text, reply_markup=profile_kb())
        await call.answer()
        return

    if action == "keys":
        profiles = await repo.list_active_profiles(session, user["user_id"])
        if not profiles:
            await call.message.edit_text("У вас нет активных ключей.", reply_markup=profile_kb())
            await call.answer()
            return
        parts = []
        for p in profiles:
            server_name = p.get("server_name") or str(p.get("server_id"))
            key_name = f"{p.get('protocol')}_{server_name}"
            parts.append(
                f"🔑 {key_name}\n"
                f"Действует до: {format_dt(p.get('access_until'))}\n"
                f"Ключ: <code>{p.get('config_uri') or '-'}</code>"
            )
        text = "\n\n──────────\n\n".join(parts)
        await call.message.edit_text(text, reply_markup=profile_kb())
        await call.answer()
        return

    await call.answer("Раздел будет доступен позже.", show_alert=True)


@router.callback_query(F.data.in_({"payhist:prev", "payhist:next"}))
async def payhist_nav(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "payhist":
        await call.answer()
        return
    history = await repo.load_payment_history(session, user["user_id"], limit=10)
    if not history:
        await call.message.edit_text("История оплат пуста.", reply_markup=None)
        await call.answer()
        return
    payload = user.get("payload") or {}
    index = int((payload.get("payhist") or {}).get("index") or 0)
    total = len(history)
    if call.data == "payhist:prev":
        index = (index - 1) % total
    else:
        index = (index + 1) % total
    await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": index})
    await session.commit()
    text = format_payment(history[index], index + 1, total)
    try:
        await call.message.edit_text(text, reply_markup=payments_kb(index + 1, total, bool(history[index].get("tg_file_id"))))
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "payhist:file")
async def payhist_file(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "payhist":
        await call.answer()
        return
    history = await repo.load_payment_history(session, user["user_id"], limit=10)
    if not history:
        await call.answer()
        return
    payload = user.get("payload") or {}
    index = int((payload.get("payhist") or {}).get("index") or 0)
    index = max(0, min(index, len(history) - 1))
    item = history[index]
    tg_file_id = item.get("tg_file_id")
    if not tg_file_id:
        await call.answer("Файл не найден", show_alert=True)
        return
    mime = (item.get("mime_type") or "").lower()
    caption = f"Оплата #{item['id']} — {item.get('amount_minor')} {item.get('currency') or 'RUB'}"
    if mime.startswith("image/"):
        await bot.send_photo(user["chat_id"], tg_file_id, caption=caption)
    else:
        await bot.send_document(user["chat_id"], tg_file_id, caption=caption)
    await call.answer()


@router.callback_query(F.data == "payhist:back")
async def payhist_back(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    profiles = await repo.list_active_profiles(session, user["user_id"])
    balance = await repo.get_balance(session, user["user_id"])
    settings = await repo.get_user_settings(session, user["user_id"])
    text = build_profile_text(user, profiles, balance, settings)
    await repo.set_state_clear(session, call.from_user.id, "profile")
    await session.commit()
    await call.message.edit_text(text, reply_markup=profile_kb())
    await call.answer()
