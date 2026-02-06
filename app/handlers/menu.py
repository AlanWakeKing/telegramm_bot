from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo

router = Router()


def build_menu(role: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")],
        [
            InlineKeyboardButton(text="💳 Оплата доступа", callback_data="menu:pay"),
            InlineKeyboardButton(text="🌐 Подключить VPN", callback_data="menu:connect"),
        ],
        [
            InlineKeyboardButton(text="🤝 Пригласи друга", callback_data="menu:ref"),
            InlineKeyboardButton(text="🏷️ Промокод", callback_data="menu:promo"),
        ],
        [
            InlineKeyboardButton(text="✉️ Написать админу", callback_data="menu:support"),
            InlineKeyboardButton(text="🌍 Change language", callback_data="menu:lang"),
        ],
    ]
    if role == "admin":
        rows.append([InlineKeyboardButton(text="🛠 Админ панель", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_menu(message: Message, session: AsyncSession, role: str):
    text = "✅ Админ-меню" if role == "admin" else "✅ Меню"
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
                reply_markup=build_menu(role),
            )
            return
    except Exception:
        pass
    sent = await message.answer(text, reply_markup=build_menu(role))
    await repo.set_state_payload(session, message.from_user.id, "menu", "ui", {"screen_message_id": sent.message_id})
    await session.commit()


@router.message(CommandStart())
@router.message(F.text == "🏠 Меню")
async def cmd_start(message: Message, session: AsyncSession):
    referrer_id = None
    if message.text and message.text.startswith("/start"):
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref"):
            try:
                ref_token = parts[1][3:]
                if ref_token.upper().startswith("REF"):
                    referrer_id = int(ref_token[3:])
                else:
                    referrer_id = int(ref_token)
            except Exception:
                referrer_id = None
    user = await repo.upsert_user(
        session,
        message.from_user.id,
        message.chat.id,
        message.from_user.username,
        referrer_id=referrer_id,
    )
    await repo.ensure_session(session, message.from_user.id)
    await session.commit()

    await render_menu(message, session, user["role"])


@router.callback_query(F.data.startswith("menu:"))
async def menu_actions(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    action = call.data.split(":")[1]
    if action == "profile":
        from . import profile as profile_handler
        await profile_handler.profile(call.message, session)
        await call.answer()
        return
    if action == "pay":
        from . import balance as balance_handler
        await balance_handler.show_balance(call.message, session)
        await call.answer()
        return
    if action == "connect":
        from . import buy as buy_handler
        await buy_handler.buy_start(call.message, session)
        await call.answer()
        return
    if action == "admin" and user.get("role") != "admin":
        await call.answer("Недостаточно прав", show_alert=True)
        return
    if action == "admin":
        await call.message.edit_text("Админ-панель будет добавлена позже.", reply_markup=build_menu(user.get("role", "user")))
        await call.answer()
        return
    if action == "ref":
        me = await call.message.bot.get_me()
        ref_code = user.get("referral_code") or f"REF{user['user_id']}"
        ref_link = f"https://t.me/{me.username}?start=ref{ref_code}"
        await call.message.edit_text(
            f"🤝 Пригласи друга\n\n"
            f"Ваша реферальная ссылка:\n{ref_link}\n\n"
            f"Отправьте её друзьям — после регистрации и оплаты они закрепятся за вами.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        await call.answer()
        return
    if action == "promo":
        await call.message.edit_text(
            "🏷️ Промокод\n\nФункция будет доступна позже.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        await call.answer()
        return
    if action == "support":
        admins = await repo.load_admin_ids(session)
        if admins:
            admin_list = "\n".join([f"- {a}" for a in admins])
        else:
            admin_list = "Администраторы не настроены."
        await call.message.edit_text(
            "✉️ Написать админу\n\n"
            "Вы можете написать администратору прямо здесь.\n"
            "ID админов:\n"
            f"{admin_list}\n\n"
            "Скоро добавим форму обращения.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        await call.answer()
        return
    if action == "lang":
        await call.message.edit_text(
            "🌍 Change language\n\nФункция будет доступна позже.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        await call.answer()
        return
    await call.answer("Раздел будет доступен позже.", show_alert=True)
