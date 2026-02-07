from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo
from .screen import edit_screen

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


async def render_menu(message: Message, session: AsyncSession, role: str, tg_user_id: int | None = None):
    text = "✅ Админ-меню" if role == "admin" else "✅ Меню"
    user_id = tg_user_id or message.from_user.id
    try:
        user = await repo.load_user_with_session(session, user_id)
        if user:
            await repo.process_referral_pending(session, user["user_id"])
            await session.commit()
    except Exception:
        pass
    await edit_screen(message, session, text, reply_markup=build_menu(role), tg_user_id=tg_user_id)


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
                    ref_token = ref_token[3:]
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

    await render_menu(message, session, user["role"], tg_user_id=message.from_user.id)


@router.callback_query(F.data.startswith("menu:"))
async def menu_actions(call: CallbackQuery, session: AsyncSession):
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer()
        return
    action = call.data.split(":")[1]
    if action == "profile":
        from . import profile as profile_handler
        await profile_handler.profile(call.message, session, tg_user_id=call.from_user.id)
        await call.answer()
        return
    if action == "pay":
        from . import balance as balance_handler
        await balance_handler.show_balance(call.message, session, tg_user_id=call.from_user.id)
        await call.answer()
        return
    if action == "connect":
        from . import buy as buy_handler
        await buy_handler.buy_start(call.message, session, tg_user_id=call.from_user.id)
        await call.answer()
        return
    if action == "admin" and user.get("role") != "admin":
        await call.answer("Недостаточно прав", show_alert=True)
        return
    if action == "admin":
        await edit_screen(call.message, session, "Админ-панель будет добавлена позже.", reply_markup=build_menu(user.get("role", "user")))
        await call.answer()
        return
    if action == "ref":
        from . import profile as profile_handler
        text, kb = await profile_handler.build_referral_view(session, call.message.bot, user, "nav:menu")
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

    if action == "promo":
        await edit_screen(
            call.message,
            session,
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
        await edit_screen(
            call.message,
            session,
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
        await edit_screen(
            call.message,
            session,
            "🌍 Change language\n\nФункция будет доступна позже.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        await call.answer()
        return
    await call.answer("Раздел будет доступен позже.", show_alert=True)
