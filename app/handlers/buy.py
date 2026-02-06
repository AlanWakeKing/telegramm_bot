from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from ..services import repo
from .menu import build_menu

router = Router()


def proto_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="WireGuard", callback_data="buy:proto:wireguard"), InlineKeyboardButton(text="Shadowsocks", callback_data="buy:proto:shadowsocks")],
        [InlineKeyboardButton(text="VLESS", callback_data="buy:proto:vless"), InlineKeyboardButton(text="Outline", callback_data="buy:proto:outline")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="buy:cancel")],
    ])


def servers_keyboard(servers: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for s in servers:
        active = int(s.get("active_keys") or 0)
        capacity = s.get("capacity")
        if capacity and int(capacity) > 0:
            pct = round((active / int(capacity)) * 100)
            if pct < 0:
                pct = 0
            label_load = f" [{pct}%]"
        else:
            label_load = f" [{active}]"
        label = f"{s['name']}{' ('+s['country']+')' if s['country'] else ''}{label_load}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"buy:srv:{s['id']}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="buy:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="buy:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        price = int(p["price_minor"] or 0)
        label = f"{p['title']} — {price} RUB / {p['duration_days']} дн."
        rows.append([InlineKeyboardButton(text=label, callback_data=f"buy:plan:{p['id']}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="buy:back"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="buy:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help:stub")]
    ])


def instructions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Инструкции", callback_data="help:stub")],
        [InlineKeyboardButton(text="↩️ В меню", callback_data="nav:menu")],
    ])


def need_balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплата доступа", callback_data="menu:pay")],
        [InlineKeyboardButton(text="↩️ В меню", callback_data="nav:menu")],
    ])


async def edit_screen(message: Message, session: AsyncSession, text: str, reply_markup: InlineKeyboardMarkup | None = None):
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
    await repo.set_state_payload(session, message.from_user.id, "menu", "ui", {"screen_message_id": sent.message_id})
    await session.commit()


@router.message(F.text == "🌐 Подключить VPN")
async def buy_start(message: Message, session: AsyncSession):
    await repo.set_state_clear(session, message.from_user.id, "buy_protocol")
    await session.commit()

    text = (
        "ШАГ 1 — Выбор протокола подключения\n\n"
        "Я предлагаю три протокола подключения: VLESS, ShadowSocks,Outline и Wireguard.\n\n"
        "Рекомендуется использовать протокол VLESS — на нём работает режим DOUBLEVPN. "
        "Этот режим использует сразу несколько серверов одновременно, при каждом включении VPN "
        "он меняет сервер автоматически, без необходимости менять ключ. Для айпи и доменов рф "
        "трафик идет в обход ВПН с сервера рф - это сделано специально что бы не ломались сайты "
        "и мессенджеры.\n\n"
        "Протоколы ShadowSocks или Outline или Wireguard — резервные.\n\n"
        "При смене протокола или сервера выдается новый ключ, а предыдущий аннулируется.\n\n"
        "Если вам нужен постоянный российский IP - такой сервер доступен в протоколе OutLine.\n"
    )
    await edit_screen(message, session, text, reply_markup=proto_keyboard())


@router.callback_query(F.data.startswith("buy:"))
async def buy_callbacks(call: CallbackQuery, session: AsyncSession):
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer("Нет сессии")
        return

    if action == "cancel":
        await repo.set_state_clear(session, call.from_user.id, "menu")
        await session.commit()
        await call.message.edit_text("Отменено.", reply_markup=None)
        from .menu import render_menu
        await render_menu(call.message, session, user.get("role", "user"))
        await call.answer()
        return

    if action == "back":
        await repo.set_state_clear(session, call.from_user.id, "buy_protocol")
        await session.commit()
        await call.message.edit_text("ШАГ 1 — Выбор протокола подключения\n\n"
        "Я предлагаю три протокола подключения: VLESS, ShadowSocks,Outline и Wireguard.\n\n"
        "Рекомендуется использовать протокол VLESS — на нём работает режим DOUBLEVPN. "
        "Этот режим использует сразу несколько серверов одновременно, при каждом включении VPN "
        "он меняет сервер автоматически, без необходимости менять ключ. Для айпи и доменов рф "
        "трафик идет в обход ВПН с сервера рф - это сделано специально что бы не ломались сайты "
        "и мессенджеры.\n\n"
        "Протоколы ShadowSocks или Outline или Wireguard — резервные.\n\n"
        "При смене протокола или сервера выдается новый ключ, а предыдущий аннулируется.\n\n"
        "Если вам нужен постоянный российский IP - такой сервер доступен в протоколе OutLine.\n", reply_markup=proto_keyboard())
        await call.answer()
        return

    if action == "proto" and len(parts) == 3:
        protocol = parts[2]
        await repo.set_state_payload(session, call.from_user.id, "buy_server", "connect", {"protocol": protocol})
        servers = await repo.list_servers(session)
        await session.commit()

        if not servers:
            await call.message.edit_text("⚠️ Серверов пока нет.\nНапишите в 💬 Поддержка.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="buy:cancel")]]))
            await call.answer()
            return

        await call.message.edit_text("ШАГ 2 — Выбор сервера подключения\n"
																			"Рекомендую использовать сервера DOUBLEVPN — это сразу несколько серверов в одном."
																			"Вы один раз создаёте ключ, и сервер автоматически меняется при каждом включении/выключении VPN.\n\n"
																			"В квадратных скобках указана заселённость сервера: чем цифра меньше — тем лучше.\n\n"

																			"Если вам нужен постоянный IP-адрес конкретной страны — выберите конкретный сервер.\n"
																			"В любой другой ситуации выбирайте менее заселенный сервер DOUBLEVPN.",
                   reply_markup=servers_keyboard(servers))
        await call.answer()
        return

    if action == "srv" and len(parts) == 3:
        server_id = int(parts[2])
        await repo.set_state_payload(session, call.from_user.id, "buy_plan", "connect", {"server_id": server_id})
        plans = await repo.list_plans(session)
        await session.commit()

        if not plans:
            await call.message.edit_text("⚠️ Тарифов пока нет.\nНапишите в 💬 Поддержка.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="buy:cancel")]]))
            await call.answer()
            return

        await call.message.edit_text("🛒 Покупка VPN\n\n3/3 Выберите тариф:", reply_markup=plans_keyboard(plans))
        await call.answer()
        return

    if action == "plan" and len(parts) == 3:
        plan_id = int(parts[2])
        plan = await repo.load_plan(session, plan_id)
        if not plan:
            await call.answer("Тариф не найден")
            return

        await repo.set_state_payload(session, call.from_user.id, "buy_plan", "buy", {"plan_id": plan_id})
        await session.commit()

        is_trial = int(plan.get("price_minor") or 0) == 0 or (plan.get("code") or "").startswith("trial")
        payload = user.get("payload") or {}
        connect = payload.get("connect") or {}
        protocol = connect.get("protocol")
        server_id = connect.get("server_id")

        if is_trial:
            used = await repo.has_trial_used(session, user["user_id"])
            if used:
                await call.message.edit_text("Пробный доступ уже был активирован ранее.")
                await call.answer()
                return
            access_until = datetime.now(timezone.utc) + timedelta(days=int(plan.get("duration_days") or 0))
            config_uri = await repo.create_vpn_profile_stub(
                session,
                user["user_id"],
                protocol,
                server_id,
                "trial",
                access_until=access_until,
            )
            await repo.set_state_clear(session, call.from_user.id, "menu")
            await repo.log_event(session, "user_actions", "info", user["tg_user_id"], user["user_id"], "trial_issued", None, {"plan_id": plan_id})
            await session.commit()

            await call.message.edit_text(
                f"✅ Пробный доступ активирован.\nВаш ключ (заглушка):\n{config_uri}",
                reply_markup=instructions_keyboard(),
            )
            await call.answer()
            return

        price = int(plan.get("price_minor") or 0)
        balance = await repo.get_balance(session, user["user_id"])
        if balance < price:
            await call.message.edit_text(
                f"Недостаточно средств. Нужно {price} ₽, у вас {balance} ₽.\n\nПополните баланс.",
                reply_markup=need_balance_kb(),
            )
            await call.answer()
            return

        new_balance = await repo.apply_balance_delta(session, user["user_id"], -price, "buy_key", {"plan_id": plan_id})
        access_until = datetime.now(timezone.utc) + timedelta(days=int(plan.get("duration_days") or 0))
        config_uri = await repo.create_vpn_profile_stub(
            session,
            user["user_id"],
            protocol,
            server_id,
            "paid",
            access_until=access_until,
        )
        await repo.set_state_clear(session, call.from_user.id, "menu")
        await repo.log_event(session, "payments", "info", user["tg_user_id"], user["user_id"], "balance_debit", None, {"plan_id": plan_id, "amount": price})
        await session.commit()

        await call.message.edit_text(
            f"✅ Ключ выдан.\nВаш ключ (заглушка):\n{config_uri}\n\nОстаток баланса: {new_balance} ₽",
            reply_markup=instructions_keyboard(),
        )
        await call.answer()
        return

    await call.answer("Неизвестная команда")
