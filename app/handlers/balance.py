from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
import secrets

from ..services import repo
from .menu import build_menu, render_menu
from .screen import edit_screen

router = Router()


def access_payment_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Баланс", callback_data="paymenu:balance"),
            InlineKeyboardButton(text="Продление", callback_data="paymenu:renew"),
        ],
        [InlineKeyboardButton(text="В меню ↩️", callback_data="paymenu:menu")],
    ])


def balance_menu_kb(balance: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Ваш баланс: {balance} ₽", callback_data="paymenu:noop")],
        [InlineKeyboardButton(text="➕ Пополнить", callback_data="topup:start")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="topup:back")],
    ])


def topup_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="500 ₽", callback_data="topup:amount:500"),
            InlineKeyboardButton(text="1000 ₽", callback_data="topup:amount:1000"),
        ],
        [
            InlineKeyboardButton(text="2000 ₽", callback_data="topup:amount:2000"),
            InlineKeyboardButton(text="5000 ₽", callback_data="topup:amount:5000"),
        ],
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data="topup:back"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="topup:cancel"),
        ],
    ])


def topup_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплата переводом", callback_data="topup:method:transfer_link")],
        [InlineKeyboardButton(text="Оплата криптой", callback_data="topup:method:crypto")],
        [InlineKeyboardButton(text="Оплата рублями СБП", callback_data="topup:method:sbp_stub")],
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data="topup:back"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="topup:cancel"),
        ],
    ])


def renew_kb(index: int, total: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️", callback_data="renew:prev"),
                InlineKeyboardButton(text=f"{index}/{total}", callback_data="renew:noop"),
                InlineKeyboardButton(text="➡️", callback_data="renew:next"),
            ],
            [InlineKeyboardButton(text="✅ Продлить", callback_data="renew:pick")],
            [InlineKeyboardButton(text="↩️ В меню", callback_data="paymenu:menu")],
        ]
    )


def renew_plans_kb(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        price = int(p.get("price_minor") or 0)
        code = (p.get("code") or "").lower()
        if price == 0 or code.startswith("trial"):
            continue
        rows.append([InlineKeyboardButton(
            text=f"{p['title']} — {price} ₽ / {p['duration_days']} дн.",
            callback_data=f"renew:plan:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="renew:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def format_profile(p: dict, idx: int, total: int) -> str:
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
        f"Ключ: <code>{config_uri}</code>\n"
    )


@router.message(F.text == "💳 Оплата доступа")
async def show_balance(message: Message, session: AsyncSession, tg_user_id: int | None = None):
    user_id = tg_user_id or message.from_user.id
    user = await repo.load_user_with_session(session, user_id)
    if not user:
        await edit_screen(message, session, "Сессия не найдена. Нажми /start", tg_user_id=user_id)
        return
    balance = await repo.get_balance(session, user["user_id"])
    info = (
        "Стоимость подписки:\n"
        "- 1 месяц – 150 рублей.\n"
        "P.S: Оплата по СБП может иметь комиссию за перевод.\n\n"
        "Как купить:\n\n"
        "1. Перейдите в раздел «Баланс» и пополните свой счет.\n\n"
        "2. После успешного пополнения баланса, откройте раздел «Продление», "
        "выберите необходимый срок подписки. После этого доступ сразу откроется."
    )
    await edit_screen(message, session, f"{info}\n\nВаш баланс: {balance} ₽", reply_markup=access_payment_menu_kb(), tg_user_id=user_id)


@router.callback_query(F.data == "paymenu:balance")
async def balance_details(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    balance = await repo.get_balance(session, user["user_id"])
    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await edit_screen(
        call.message,
        session,
        "Это ваш баланс.\n"
        "- Вы пополняете его рублями через Перевод, либо криптой, либо через покупку YooMoney.\n\n"
        "После успешного пополнения баланса, перейдите в раздел «Продление» и выберите необходимый срок подписки.\n"
        "После этого доступ сразу откроется.",
        reply_markup=balance_menu_kb(balance),
    )
    await call.answer()


@router.callback_query(F.data == "topup:start")
async def topup_start(call: CallbackQuery, session: AsyncSession):
    await repo.set_state_clear(session, call.from_user.id, "topup_method")
    await session.commit()
    await edit_screen(call.message, session, "Способ пополнения:", reply_markup=topup_method_kb())
    await call.answer()


@router.callback_query(F.data.startswith("topup:method:"))
async def topup_method(call: CallbackQuery, session: AsyncSession):
    method = call.data.split(":")[2]
    await repo.set_state_payload(session, call.from_user.id, "topup_amount", "topup", {"method": method})
    await session.commit()
    await edit_screen(call.message, session, "Выберите сумму пополнения:", reply_markup=topup_amount_kb())
    await call.answer()


@router.callback_query(F.data.startswith("topup:amount:"))
async def topup_amount(call: CallbackQuery, session: AsyncSession, bot):
    amount = int(call.data.split(":")[2])
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return

    payload = user.get("payload") or {}
    method = (payload.get("topup") or {}).get("method")
    if not method:
        await call.answer("Способ не выбран", show_alert=True)
        return

    if method in ("transfer", "transfer_link"):
        code = f"PAY-{secrets.token_hex(3).upper()}"
        link = None
        if method == "transfer_link":
            link = f"https://t-qr.ru/p.php?t=ucuulgfmmobmmrx&i={code}&n=ALEKSEY&b=t-bank"
        await repo.set_state_payload(
            session,
            call.from_user.id,
            "topup_proof",
            "topup",
            {"amount": amount, "method": "transfer", "code": code},
        )
        await session.commit()

        if link:
            text = (
                f"Ссылка на перевод:\n{link}\n\n"
                f"Сумма: {amount} ₽\n"
                f"Код платежа: {code}\n\n"
                f"Переведите {amount} ₽ и укажите код в комментарии к переводу.\n"
                f"После оплаты пришлите фото/скрин/квитанцию (PDF)."
            )
        else:
            text = (
                f"Сумма: {amount} ₽\n"
                f"Код платежа: {code}\n\n"
                f"Переведите {amount} ₽ и укажите код в комментарии к переводу.\n"
                f"После оплаты пришлите фото/скрин/квитанцию (PDF)."
            )

        await edit_screen(
            call.message,
            session,
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="topup:cancel")]
            ]),
            disable_web_page_preview=True,
        )
        try:
            await call.answer()
        except Exception:
            pass
        return

    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await edit_screen(call.message, session, "Этот способ оплаты временно недоступен.", reply_markup=access_payment_menu_kb())
    await call.answer()


@router.callback_query(F.data == "topup:back")
async def topup_back(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    balance = await repo.get_balance(session, user["user_id"])
    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await edit_screen(call.message, session, f"Ваш баланс: {balance} ₽", reply_markup=access_payment_menu_kb())
    await call.answer()


@router.callback_query(F.data == "topup:cancel")
async def topup_cancel(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await render_menu(call.message, session, user.get("role", "user"), tg_user_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "paymenu:renew")
async def renew_start(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    profiles = await repo.list_active_profiles(session, user["user_id"])
    if not profiles:
        await edit_screen(call.message, session, "У вас нет активных ключей.", reply_markup=access_payment_menu_kb())
        await call.answer()
        return
    index = 0
    await repo.set_state_payload(session, call.from_user.id, "renew", "renew", {"index": index})
    await session.commit()
    total = len(profiles)
    text = format_profile(profiles[index], index + 1, total)
    await edit_screen(call.message, session, text, reply_markup=renew_kb(index + 1, total), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.in_({"renew:prev", "renew:next"}))
async def renew_nav(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    if user.get("state") != "renew":
        await call.answer()
        return
    profiles = await repo.list_active_profiles(session, user["user_id"])
    if not profiles:
        await edit_screen(call.message, session, "У вас нет активных ключей.")
        await call.answer()
        return
    payload = user.get("payload") or {}
    index = int((payload.get("renew") or {}).get("index") or 0)
    total = len(profiles)
    if call.data == "renew:prev":
        index = (index - 1) % total
    else:
        index = (index + 1) % total
    await repo.set_state_payload(session, call.from_user.id, "renew", "renew", {"index": index})
    await session.commit()
    text = format_profile(profiles[index], index + 1, total)
    await edit_screen(call.message, session, text, reply_markup=renew_kb(index + 1, total), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "renew:pick")
async def renew_select(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "renew":
        await call.answer()
        return
    profiles = await repo.list_active_profiles(session, user["user_id"])
    if not profiles:
        await edit_screen(call.message, session, "У вас нет активных ключей.")
        await call.answer()
        return
    payload = user.get("payload") or {}
    index = int((payload.get("renew") or {}).get("index") or 0)
    index = max(0, min(index, len(profiles) - 1))
    selected = profiles[index]
    if (selected.get("provider_meta") or {}).get("source") == "trial":
        await call.answer("Пробные ключи продлевать нельзя.", show_alert=True)
        return
    await repo.set_state_payload(session, call.from_user.id, "renew_plan", "renew", {"index": index, "profile_id": selected["id"]})
    await session.commit()
    plans = await repo.list_plans(session)
    if not plans:
        await edit_screen(call.message, session, "Тарифы не найдены.")
        await call.answer()
        return
    await edit_screen(
        call.message,
        session,
        f"Выбран ключ:\n"
        f"Действует до: {format_dt(selected.get('access_until'))}\n\n"
        f"Выберите срок продления:",
        reply_markup=renew_plans_kb(plans),
    )
    await call.answer()


@router.callback_query(F.data.startswith("renew:plan:"))
async def renew_apply(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("state") != "renew_plan":
        await call.answer()
        return
    try:
        plan_id = int(call.data.split(":")[2])
    except Exception:
        await edit_screen(call.message, session, "Не удалось определить тариф.")
        await call.answer()
        return
    plan = await repo.load_plan(session, plan_id)
    if not plan:
        await edit_screen(call.message, session, "Тариф не найден.")
        await call.answer()
        return
    payload = user.get("payload") or {}
    profile_id = (payload.get("renew") or {}).get("profile_id")
    if not profile_id:
        await edit_screen(call.message, session, "Ключ не выбран.")
        await call.answer()
        return
    price = int(plan.get("price_minor") or 0)
    balance = await repo.get_balance(session, user["user_id"])
    if balance < price:
        await edit_screen(call.message, session, f"Недостаточно средств. Нужно {price} ₽, у вас {balance} ₽.")
        await call.answer()
        return

    profiles = await repo.list_active_profiles(session, user["user_id"])
    current = next((p for p in profiles if p["id"] == profile_id), None)
    base = datetime.now(timezone.utc)
    if current and current.get("access_until"):
        au = current["access_until"]
        if isinstance(au, datetime) and au > base:
            base = au
    new_until = base + timedelta(days=int(plan.get("duration_days") or 0))

    updated = await repo.update_profile_access_until(session, profile_id, new_until)
    if not updated:
        await edit_screen(call.message, session, "Не удалось продлить ключ. Попробуйте позже.")
        await call.answer()
        return
    new_balance = await repo.apply_balance_delta(session, user["user_id"], -price, "renew", {"plan_id": plan_id, "profile_id": profile_id})
    await repo.log_event(session, "payments", "info", user["tg_user_id"], user["user_id"], "renewed", None, {"plan_id": plan_id, "profile_id": profile_id, "amount": price})
    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()

    await edit_screen(
        call.message,
        session,
        f"✅ Продление успешно.\nДействует до: {format_dt(new_until)}\nБаланс: {new_balance} ₽",
        reply_markup=build_menu(user.get("role", "user")),
    )
    await call.answer()


@router.callback_query(F.data == "paymenu:menu")
async def back_to_menu(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await render_menu(call.message, session, user.get("role", "user"), tg_user_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data.in_({"renew:back", "renew:exit"}))
async def renew_back_exit(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    if call.data == "renew:back":
        profiles = await repo.list_active_profiles(session, user["user_id"])
        if not profiles:
            await repo.set_state_clear(session, call.from_user.id, "menu")
            await session.commit()
            await edit_screen(call.message, session, "У вас нет активных ключей.")
            await call.answer()
            return
        payload = user.get("payload") or {}
        index = int((payload.get("renew") or {}).get("index") or 0)
        index = max(0, min(index, len(profiles) - 1))
        await repo.set_state_payload(session, call.from_user.id, "renew", "renew", {"index": index})
        await session.commit()
        text = format_profile(profiles[index], index + 1, len(profiles))
        await edit_screen(call.message, session, text, reply_markup=renew_kb(index + 1, len(profiles)), parse_mode="HTML")
        await call.answer()
        return

    await repo.set_state_clear(session, call.from_user.id, "menu")
    await session.commit()
    await render_menu(call.message, session, user.get("role", "user"), tg_user_id=call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "renew:noop")
async def renew_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "paymenu:noop")
async def paymenu_noop(call: CallbackQuery):
    await call.answer()
