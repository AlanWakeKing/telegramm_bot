from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from ..services import repo
from .screen import edit_screen, edit_screen_by_user

router = Router()


@router.message(F.text == "/chatid")
async def chat_id(message: Message, session: AsyncSession):
    await message.answer(f"Chat ID: {message.chat.id}")


@router.callback_query(F.data == "help:stub")
async def help_stub(call: CallbackQuery, session: AsyncSession):
    await edit_screen(call.message, session, "❓ Инструкции скоро будут добавлены.")
    await call.answer()


@router.callback_query(F.data == "nav:menu")
async def nav_menu(call: CallbackQuery, session: AsyncSession):
    from .menu import render_menu
    from ..services import repo
    u = await repo.load_user_with_session(session, call.from_user.id)
    if not u:
        try:
            await call.answer()
        except TelegramBadRequest:
            pass
        return
    await render_menu(call.message, session, u.get("role", "user"), tg_user_id=call.from_user.id)
    try:
        await call.answer()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("admin:"))
async def admin_stub(call: CallbackQuery, session: AsyncSession):
    await edit_screen(call.message, session, "Раздел будет доступен позже.")
    await call.answer()


@router.callback_query(F.data.startswith("support:"))
async def support_admin_actions(call: CallbackQuery, session: AsyncSession):
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        ticket_id = int(parts[2]) if len(parts) > 2 else 0
    except Exception:
        ticket_id = 0

    admin_group_id = await repo.get_admin_group_id(session)
    if call.message.chat.id != admin_group_id:
        await call.answer("Недоступно", show_alert=True)
        return

    admin_ids = await repo.load_admin_ids(session)
    if call.from_user.id not in admin_ids:
        await call.answer("Недостаточно прав", show_alert=True)
        return
    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user:
        await call.answer("Нет сессии. Откройте /start в личных сообщениях.", show_alert=True)
        return

    ticket = await repo.get_support_ticket(session, ticket_id)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return

    display_id = ticket.get("user_ticket_id") or ticket_id

    if action == "reply":
        await repo.set_state_payload(session, call.from_user.id, "support_reply", "support", {"ticket_id": ticket_id})
        await session.commit()
        await call.answer()
        try:
            await call.message.reply(f"Введите ответ на обращение #{display_id}.")
        except Exception:
            pass
        return

    if action == "close":
        await repo.close_support_ticket(session, ticket_id)
        await session.commit()
        try:
            await call.message.bot.send_message(
                ticket["chat_id"],
                f"🔒 Обращение #{display_id} закрыто администратором.",
            )
        except Exception:
            pass
        try:
            await call.message.edit_text(f"Обращение #{display_id} закрыто.")
        except Exception:
            pass
        await call.answer()
        return

    await call.answer("Неизвестное действие", show_alert=True)


@router.message(F.text)
async def unknown(message: Message, session: AsyncSession):
    user = await repo.load_user_with_session(session, message.from_user.id)
    admin_group_id = await repo.get_admin_group_id(session)
    admin_ids = await repo.load_admin_ids(session)

    # Admin reply flow in admin group
    if message.chat.id == admin_group_id:
        # Ignore non-admins in admin group
        if message.from_user.id not in admin_ids:
            return
        if user and user.get("state") == "support_reply":
            payload = user.get("payload") or {}
            support_state = payload.get("support") or {}
            ticket_id = int(support_state.get("ticket_id") or 0)
            ticket = await repo.get_support_ticket(session, ticket_id)
            if ticket:
                display_id = ticket.get("user_ticket_id") or ticket_id
                await repo.add_support_message(session, ticket_id, "admin", message.text)
                await session.commit()
                try:
                    await edit_screen_by_user(
                        message.bot,
                        ticket["chat_id"],
                        session,
                        ticket["tg_user_id"],
                        f"💬 Ответ поддержки (обращение #{display_id}):\n\n{message.text}",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="К обращениям", callback_data="profile:tickets")],
                            [InlineKeyboardButton(text="В меню", callback_data="nav:menu")],
                        ]),
                    )
                except Exception:
                    pass
                await repo.set_state_clear(session, message.from_user.id, "menu")
                await session.commit()
                await message.reply(f"Ответ отправлен пользователю (обращение #{display_id}).")
            else:
                await message.reply("Обращение не найдено.")
        # Do not respond to other group messages
        return

    # User creates/updates support ticket
    if user and user.get("state") == "support_wait":
        payload = user.get("payload") or {}
        support_state = payload.get("support") or {}
        ticket_id = int(support_state.get("ticket_id") or 0)

        open_ticket = None
        if ticket_id:
            t = await repo.get_support_ticket(session, ticket_id)
            if t and int(t.get("user_id") or 0) == int(user["user_id"]) and t.get("status") == "open":
                open_ticket = t

        if not open_ticket:
            open_count = await repo.count_open_tickets_for_user(session, user["user_id"])
            if open_count >= 5:
                await edit_screen(message, session, "Достигнут лимит открытых обращений (5). Закройте старые обращения.")
                try:
                    await message.delete()
                except Exception:
                    pass
                return
            open_ticket = await repo.add_support_ticket(session, user, message.text)
        else:
            await repo.add_support_message(session, open_ticket["id"], "user", message.text)
        await session.commit()

        display_ticket_id = open_ticket.get("user_ticket_id") or open_ticket["id"]
        text_admin = (
            "📩 <b>Новое сообщение в поддержку</b>\n\n"
            f"Обращение: <code>#{display_ticket_id}</code>\n"
            f"Пользователь: @{user.get('username') or '-'} ({user['tg_user_id']})\n\n"
            f"{message.text}"
        )
        try:
            await message.bot.send_message(
                admin_group_id,
                text_admin,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Ответить", callback_data=f"support:reply:{open_ticket['id']}"),
                    InlineKeyboardButton(text="Закрыть", callback_data=f"support:close:{open_ticket['id']}"),
                ]]),
            )
        except Exception as exc:
            try:
                await repo.log_event(
                    session,
                    "user_actions",
                    "error",
                    user.get("tg_user_id"),
                    user.get("user_id"),
                    "support_send_failed",
                    str(exc),
                    {"admin_group_id": admin_group_id, "ticket_id": open_ticket.get("id")},
                )
            except Exception:
                pass

        from .menu import build_menu
        await edit_screen(
            message,
            session,
            f"✅ Сообщение отправлено в поддержку. Номер обращения #{display_ticket_id}.",
            reply_markup=build_menu(user.get("role", "user")),
        )
        try:
            await message.delete()
        except Exception:
            pass
        return

    if user and user.get("state") == "promo_wait":
        ok, text, _new_balance = await repo.redeem_promo(session, user["user_id"], message.text)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="nav:menu")]]
        )
        if ok:
            await repo.set_state_clear(session, message.from_user.id, "menu")
            await session.commit()
            from .menu import render_menu
            await render_menu(message, session, user.get("role", "user"), tg_user_id=message.from_user.id)
            await edit_screen(message, session, text, reply_markup=kb)
            try:
                await message.delete()
            except Exception:
                pass
            return
        await edit_screen(message, session, text, reply_markup=kb)
        try:
            await message.delete()
        except Exception:
            pass
        return
    await edit_screen(message, session, "Команда не распознана. Откройте меню: /start")
