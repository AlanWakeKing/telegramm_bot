from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo
from .screen import edit_screen, edit_screen_by_user

router = Router()


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Реферальная ссылка", callback_data="profile:ref")],
        [
            InlineKeyboardButton(text="История оплат", callback_data="profile:payments"),
            InlineKeyboardButton(text="Уведомления", callback_data="profile:notify"),
        ],
        [InlineKeyboardButton(text="Активные ключи", callback_data="profile:keys")],
        [InlineKeyboardButton(text="↩️ В меню", callback_data="nav:menu")],
    ])


def profile_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ В профиль", callback_data="profile:back")]
    ])


def referral_kb(share_text: str, back_callback: str, can_withdraw: bool) -> InlineKeyboardMarkup:
    withdraw_text = "Перевод на баланс" if can_withdraw else "У вас недостаточно средств для вывода"
    withdraw_cb = "ref:withdraw" if can_withdraw else "ref:withdraw_no"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить ссылку", switch_inline_query=share_text)],
        [InlineKeyboardButton(text=withdraw_text, callback_data=withdraw_cb)],
        [InlineKeyboardButton(text="↩️ Назад", callback_data=back_callback)],
    ])


def referral_admin_kb(req_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"refwd:approve:{req_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"refwd:reject:{req_id}"),
        ]
    ])


def payments_kb(index: int, total: int, has_file: bool, is_open: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⬅️", callback_data="payhist:prev"),
            InlineKeyboardButton(text=f"{index}/{total}", callback_data="payhist:noop"),
            InlineKeyboardButton(text="➡️", callback_data="payhist:next"),
        ]
    ]
    if has_file:
        label = "📎 Закрыть чек" if is_open else "📎 Открыть чек"
        rows.append([InlineKeyboardButton(text=label, callback_data="payhist:file")])
    rows.append([InlineKeyboardButton(text="↩️ В профиль", callback_data="payhist:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def keys_kb(index: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    if total > 1:
        rows.append([
            InlineKeyboardButton(text="⬅️", callback_data="pkeys:prev"),
            InlineKeyboardButton(text=f"{index}/{total}", callback_data="pkeys:noop"),
            InlineKeyboardButton(text="➡️", callback_data="pkeys:next"),
        ])
    rows.append([InlineKeyboardButton(text="↩️ В профиль", callback_data="pkeys:back")])
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


def format_key(p: dict, idx: int, total: int) -> str:
    server_name = p.get("server_name") or str(p.get("server_id"))
    key_name = f"{p.get('protocol')}_{server_name}"
    created = format_dt(p.get("created_at"))
    access_until = format_dt(p.get("access_until"))
    status = "АКТИВЕН" if (p.get("status") == "active") else (p.get("status") or "-")
    config_uri = p.get("config_uri") or "-"
    return (
        f"Найдено: {total}\n\n"
        f"Выберите ключ:\n\n"
        f"🔑 Ключ: {key_name}\n"
        f"Протокол: {p.get('protocol')}\n"
        f"Сервер: {server_name}\n"
        f"Создан: {created}\n"
        f"Действует до: {access_until}\n"
        f"Статус: {status}\n"
        f"Ключ: <code>{config_uri}</code>"
    )


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
            sub_status = "истек"
        else:
            sub_status = "активен"

    notifications = "✅ включены" if settings.get("notifications_enabled") else "❌ выключены"
    language = settings.get("language") or "ru"

    return (
        "👤 Профиль\n\n"
        f"ID: {user['tg_user_id']}\n"
        f"Username: @{user.get('username') or '-'}\n\n"
        f"Статус подписки: {sub_status}\n"
        f"Действует до: {format_dt(nearest_until)}\n"
        f"Баланс: {balance} ₽\n"
        f"Активных ключей: {active_count}\n\n"
        f"Уведомления: {notifications}\n"
        f"Язык: {language}"
    )


async def build_referral_view(session: AsyncSession, bot, user: dict, back_callback: str) -> tuple[str, InlineKeyboardMarkup]:
    me = await bot.get_me()
    ref_code = user.get("referral_code") or f"REF{user['user_id']}"
    ref_link = f"https://t.me/{me.username}?start=ref{ref_code}"
    referrals = await repo.count_referrals(session, user["user_id"])
    wallet = await repo.get_referral_wallet(session, user["user_id"])
    text = (
        "Ваша реферальная ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        "Минимальная сумма на перевод с реферального счета на баланс бота составляет: 500 ₽\n"
        "Вывод средств осуществляется по заявке.\n"
        f"Количество ваших рефералов: {referrals}\n"
        f"Доступно на вывод: {wallet} ₽"
    )
    share_text = f"Моя реферальная ссылка: {ref_link}"
    return text, referral_kb(share_text, back_callback, wallet >= 500)


@router.message(F.text == "👤 Профиль")
async def profile(message: Message, session: AsyncSession, tg_user_id: int | None = None):
    user_id = tg_user_id or message.from_user.id
    user = await repo.load_user_with_session(session, user_id)
    if not user:
        await edit_screen(message, session, "Сессия не найдена. Нажми /start", tg_user_id=user_id)
        return

    profiles = await repo.list_active_profiles(session, user["user_id"])
    balance = await repo.get_balance(session, user["user_id"])
    settings = await repo.get_user_settings(session, user["user_id"])
    text = build_profile_text(user, profiles, balance, settings)
    await repo.set_state_clear(session, user_id, "profile")
    await session.commit()
    await edit_screen(message, session, text, reply_markup=profile_kb(), tg_user_id=user_id)


@router.callback_query(F.data.startswith("profile:"))
async def profile_callbacks(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer("Нет сессии", show_alert=True)
        return

    action = call.data.split(":")[1]

    if action == "ref":
        text, kb = await build_referral_view(session, bot, user, "profile:back")
        await edit_screen(
            call.message,
            session,
            text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await call.answer()
        return

    if action == "payments":
        history = await repo.load_payment_history(session, user["user_id"], limit=10)
        if not history:
            await edit_screen(call.message, session, "История оплат пуста.", reply_markup=profile_back_kb())
            await call.answer()
            return
        await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": 0, "open": False, "file_msg_id": None})
        await session.commit()
        total = len(history)
        text = format_payment(history[0], 1, total)
        await edit_screen(call.message, session, text, reply_markup=payments_kb(1, total, bool(history[0].get("tg_file_id")), False))
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
            text = f"{text}\n\n❌ Уведомления выключены. Важные сообщения могут быть пропущены."
        await edit_screen(call.message, session, text, reply_markup=profile_kb())
        await call.answer()
        return

    if action == "keys":
        profiles = await repo.list_active_profiles(session, user["user_id"])
        if not profiles:
            await edit_screen(call.message, session, "У вас нет активных ключей.", reply_markup=profile_back_kb())
            await call.answer()
            return
        await repo.set_state_payload(session, call.from_user.id, "pkeys", "pkeys", {"index": 0})
        await session.commit()
        total = len(profiles)
        text = format_key(profiles[0], 1, total)
        await edit_screen(call.message, session, text, reply_markup=keys_kb(1, total), parse_mode="HTML")
        await call.answer()
        return

    if action == "back":
        profiles = await repo.list_active_profiles(session, user["user_id"])
        balance = await repo.get_balance(session, user["user_id"])
        settings = await repo.get_user_settings(session, user["user_id"])
        text = build_profile_text(user, profiles, balance, settings)
        await repo.set_state_clear(session, call.from_user.id, "profile")
        await session.commit()
        await edit_screen(call.message, session, text, reply_markup=profile_kb())
        await call.answer()
        return

    await call.answer("Раздел будет доступен позже.", show_alert=True)


@router.callback_query(F.data.in_({"payhist:prev", "payhist:next"}))
async def payhist_nav(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "payhist":
        await call.answer()
        return
    history = await repo.load_payment_history(session, user["user_id"], limit=10)
    if not history:
        await edit_screen(call.message, session, "История оплат пуста.")
        await call.answer()
        return

    payload = user.get("payload") or {}
    payhist = payload.get("payhist") or {}
    index = int(payhist.get("index") or 0)
    open_flag = bool(payhist.get("open"))
    file_msg_id = payhist.get("file_msg_id")

    if open_flag and file_msg_id:
        try:
            await bot.delete_message(user["chat_id"], file_msg_id)
        except Exception:
            pass

    total = len(history)
    if call.data == "payhist:prev":
        index = (index - 1) % total
    else:
        index = (index + 1) % total

    await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": index, "open": False, "file_msg_id": None})
    await session.commit()
    text = format_payment(history[index], index + 1, total)
    await edit_screen(call.message, session, text, reply_markup=payments_kb(index + 1, total, bool(history[index].get("tg_file_id")), False))
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
    payhist = payload.get("payhist") or {}
    index = int(payhist.get("index") or 0)
    index = max(0, min(index, len(history) - 1))
    item = history[index]
    tg_file_id = item.get("tg_file_id")

    if not tg_file_id:
        await call.answer("Файл не найден", show_alert=True)
        return

    is_open = bool(payhist.get("open"))
    file_msg_id = payhist.get("file_msg_id")

    if is_open and file_msg_id:
        try:
            await bot.delete_message(user["chat_id"], file_msg_id)
        except Exception:
            pass
        await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": index, "open": False, "file_msg_id": None})
        await session.commit()
        text = format_payment(item, index + 1, len(history))
        await edit_screen(call.message, session, text, reply_markup=payments_kb(index + 1, len(history), True, False))
        await call.answer()
        return

    mime = (item.get("mime_type") or "").lower()
    caption = f"Оплата #{item['id']} — {item.get('amount_minor')} {item.get('currency') or 'RUB'}"
    try:
        if mime.startswith("image/"):
            sent = await bot.send_photo(user["chat_id"], tg_file_id, caption=caption)
        else:
            sent = await bot.send_document(user["chat_id"], tg_file_id, caption=caption)
    except Exception:
        sent = await bot.send_document(user["chat_id"], tg_file_id, caption=caption)

    await repo.set_state_payload(session, call.from_user.id, "payhist", "payhist", {"index": index, "open": True, "file_msg_id": sent.message_id})
    await session.commit()
    text = format_payment(item, index + 1, len(history))
    await edit_screen(call.message, session, text, reply_markup=payments_kb(index + 1, len(history), True, True))
    await call.answer()


@router.callback_query(F.data == "payhist:back")
async def payhist_back(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return

    payload = user.get("payload") or {}
    payhist = payload.get("payhist") or {}
    open_flag = bool(payhist.get("open"))
    file_msg_id = payhist.get("file_msg_id")
    if open_flag and file_msg_id:
        try:
            await bot.delete_message(user["chat_id"], file_msg_id)
        except Exception:
            pass

    profiles = await repo.list_active_profiles(session, user["user_id"])
    balance = await repo.get_balance(session, user["user_id"])
    settings = await repo.get_user_settings(session, user["user_id"])
    text = build_profile_text(user, profiles, balance, settings)
    await repo.set_state_clear(session, call.from_user.id, "profile")
    await session.commit()
    await edit_screen(call.message, session, text, reply_markup=profile_kb())
    await call.answer()


@router.callback_query(F.data.in_({"pkeys:prev", "pkeys:next"}))
async def pkeys_nav(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "pkeys":
        await call.answer()
        return
    profiles = await repo.list_active_profiles(session, user["user_id"])
    if not profiles:
        await call.answer()
        return

    payload = user.get("payload") or {}
    pkeys = payload.get("pkeys") or {}
    index = int(pkeys.get("index") or 0)
    total = len(profiles)
    if call.data == "pkeys:prev":
        index = (index - 1) % total
    else:
        index = (index + 1) % total

    await repo.set_state_payload(session, call.from_user.id, "pkeys", "pkeys", {"index": index})
    await session.commit()
    text = format_key(profiles[index], index + 1, total)
    await edit_screen(call.message, session, text, reply_markup=keys_kb(index + 1, total), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "pkeys:back")
async def pkeys_back(call: CallbackQuery, session: AsyncSession):
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
    await edit_screen(call.message, session, text, reply_markup=profile_kb())
    await call.answer()


@router.callback_query(F.data.in_({"payhist:noop", "pkeys:noop"}))
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "ref:withdraw")
async def ref_withdraw(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    wallet = await repo.get_referral_wallet(session, user["user_id"])
    if wallet < 500:
        await call.answer("У вас недостаточно средств для вывода", show_alert=True)
        return
    req_id = await repo.add_ref_withdraw_request(session, user["user_id"], wallet)
    if not req_id:
        await call.answer("Заявка уже в обработке", show_alert=True)
        return
    await session.commit()
    admin_ids = await repo.load_admin_ids(session)
    text_admin = (
        f"💸 Заявка на вывод\\n"
        f"ID: {req_id}\\n"
        f"Пользователь: @{user.get('username') or '-'} ({user['tg_user_id']})\\n"
        f"Сумма: {wallet} ₽"
    )
    for admin_id in admin_ids:
        await bot.send_message(admin_id, text_admin, reply_markup=referral_admin_kb(req_id))

    text, kb = await build_referral_view(session, bot, user, "profile:back")
    text = f"{text}\n\n✅ Заявка отправлена. Мы рассмотрим её в ближайшее время."
    await edit_screen(call.message, session, text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "ref:withdraw_no")
async def ref_withdraw_no(call: CallbackQuery):
    await call.answer("У вас недостаточно средств для вывода", show_alert=True)


@router.callback_query(F.data.startswith("refwd:"))
async def ref_withdraw_admin(call: CallbackQuery, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("role") != "admin":
        await call.answer("Недостаточно прав", show_alert=True)
        return
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    req_id = parts[2] if len(parts) > 2 else ""
    req = await repo.get_ref_withdraw_request(session, req_id)
    if not req or req.get("status") != "pending":
        await call.answer("Заявка не найдена", show_alert=True)
        return

    target_user_id = int(req.get("user_id") or 0)
    target_user = await repo.load_user_by_id(session, target_user_id)
    if not target_user:
        await repo.update_ref_withdraw_status(session, req_id, "rejected", {"reason": "user_not_found"})
        await session.commit()
        await call.answer("Пользователь не найден", show_alert=True)
        return

    if action == "approve":
        wallet = await repo.get_referral_wallet(session, target_user_id)
        if wallet < 500:
            await repo.update_ref_withdraw_status(session, req_id, "rejected", {"reason": "insufficient_wallet"})
            await session.commit()
            await edit_screen_by_user(
                bot,
                target_user["chat_id"],
                session,
                target_user["tg_user_id"],
                "❌ Заявка отклонена: недостаточно средств для вывода.",
                reply_markup=profile_back_kb(),
            )
            await call.answer("Недостаточно средств", show_alert=True)
        else:
            amount = min(wallet, int(req.get("amount") or wallet))
            new_balance = await repo.apply_balance_delta(
                session,
                target_user_id,
                amount,
                "referral_withdraw",
                {"request_id": req_id, "amount": amount},
            )
            await repo.clear_referral_wallet(session, target_user_id)
            await repo.update_ref_withdraw_status(session, req_id, "approved", {"amount": amount})
            await session.commit()
            await edit_screen_by_user(
                bot,
                target_user["chat_id"],
                session,
                target_user["tg_user_id"],
                f"✅ Заявка одобрена. На баланс зачислено {amount} ₽.\\nТекущий баланс: {new_balance} ₽",
                reply_markup=profile_back_kb(),
            )
            await call.answer("Заявка одобрена")

    elif action == "reject":
        await repo.update_ref_withdraw_status(session, req_id, "rejected", {"reason": "rejected_by_admin"})
        await session.commit()
        await edit_screen_by_user(
            bot,
            target_user["chat_id"],
            session,
            target_user["tg_user_id"],
            "❌ Заявка отклонена. Если это ошибка — обратитесь в поддержку.",
            reply_markup=profile_back_kb(),
        )
        await call.answer("Заявка отклонена")
    else:
        await call.answer("Неизвестное действие", show_alert=True)

    if call.message:
        try:
            await call.message.delete()
        except Exception:
            pass
