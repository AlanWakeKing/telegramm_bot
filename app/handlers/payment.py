from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from ..services import repo

router = Router()


def admin_payment_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"pay:approve:{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay:reject:{order_id}"),
    ]])


def instructions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Инструкции", callback_data="help:stub")]
    ])


@router.message(F.photo | F.document)
async def handle_payment_proof(message: Message, session: AsyncSession, bot):
    user = await repo.load_user_with_session(session, message.from_user.id)
    if not user or user.get("state") not in ("pay_proof", "topup_proof"):
        return

    file_id = None
    file_name = None
    mime_type = None
    file_size = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
        mime_type = message.document.mime_type
        file_size = message.document.file_size
    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_size = photo.file_size
        mime_type = "image/jpeg"

    if not file_id:
        await message.answer("Пожалуйста, отправьте фото или PDF с оплатой.")
        return

    payload = user.get("payload") or {}

    if user.get("state") == "topup_proof":
        amount = (payload.get("topup") or {}).get("amount")
        if not amount:
            await message.answer("Сумма пополнения не найдена. Начните заново.")
            return
        plan = None
        protocol = None
        server_id = None
    else:
        plan_id = (payload.get("buy") or {}).get("plan_id")
        connect = payload.get("connect") or {}
        protocol = connect.get("protocol")
        server_id = connect.get("server_id")
        plan = await repo.load_plan(session, plan_id)
        if not plan:
            await message.answer("Тариф не найден. Начните заново.")
            return

    tg_file = await bot.get_file(file_id)
    file_bytes = await bot.download_file(tg_file.file_path)
    if hasattr(file_bytes, "read"):
        data = file_bytes.read()
    elif hasattr(file_bytes, "getvalue"):
        data = file_bytes.getvalue()
    else:
        data = bytes(file_bytes)

    if user.get("state") == "topup_proof":
        order_id = await repo.insert_payment_order(
            session,
            user_id=user["user_id"],
            plan_id=None,
            amount_minor=amount,
            currency="RUB",
            meta={"type": "topup", "amount": amount, "tg_file_id": file_id},
        )
    else:
        order_id = await repo.insert_payment_order(
            session,
            user_id=user["user_id"],
            plan_id=plan_id,
            amount_minor=plan["price_minor"],
            currency=plan.get("currency") or "RUB",
            meta={"protocol": protocol, "server_id": server_id, "tg_file_id": file_id},
        )

    await repo.insert_payment_proof(session, order_id, file_id, file_name, mime_type, file_size, data)
    await repo.log_event(session, "payments", "info", user["tg_user_id"], user["user_id"], "payment_proof_uploaded", None, {"order_id": order_id})
    await repo.set_state_clear(session, message.from_user.id, "menu")
    await session.commit()

    await message.answer("Спасибо! Оплата получена на проверку. После подтверждения мы пришлём ключ.")

    admin_ids = await repo.load_admin_ids(session)
    if user.get("state") == "topup_proof":
        text = (
            f"💳 Пополнение баланса\nOrder #{order_id}\n"
            f"Пользователь: @{user.get('username') or '-'} ({user['tg_user_id']})\n"
            f"Сумма: {amount} RUB"
        )
    else:
        price = plan["price_minor"]
        text = (
            f"💳 Новая оплата\nOrder #{order_id}\n"
            f"Пользователь: @{user.get('username') or '-'} ({user['tg_user_id']})\n"
            f"Тариф: {plan['title']}\n"
            f"Сумма: {price} RUB"
        )

    proof = await repo.load_payment_proof(session, order_id)
    for admin_id in admin_ids:
        if proof and proof.get("tg_file_id"):
            mime = (proof.get("mime_type") or "").lower()
            try:
                if mime.startswith("image/") or mime == "":
                    await bot.send_photo(
                        admin_id,
                        proof["tg_file_id"],
                        caption=text,
                        reply_markup=admin_payment_keyboard(order_id),
                    )
                else:
                    await bot.send_document(
                        admin_id,
                        proof["tg_file_id"],
                        caption=text,
                        reply_markup=admin_payment_keyboard(order_id),
                    )
            except Exception:
                # fallback to document if photo failed
                await bot.send_document(
                    admin_id,
                    proof["tg_file_id"],
                    caption=text,
                    reply_markup=admin_payment_keyboard(order_id),
                )
        else:
            await bot.send_message(admin_id, text, reply_markup=admin_payment_keyboard(order_id))


@router.callback_query(F.data.startswith("pay:"))
async def handle_admin_payment(call: CallbackQuery, session: AsyncSession, bot):
    parts = call.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    order_id = int(parts[2]) if len(parts) > 2 else 0

    user = await repo.load_user_with_session(session, call.from_user.id)
    if not user or user.get("role") != "admin":
        await call.answer("Недостаточно прав")
        return

    order = await repo.load_order(session, order_id)
    if not order:
        await call.answer("Заказ не найден")
        return

    if action == "approve":
        await repo.update_order_status(session, order_id, "paid")

        if (order.get("meta") or {}).get("type") == "topup":
            amount = int((order.get("meta") or {}).get("amount") or order["amount_minor"])
            new_balance = await repo.apply_balance_delta(session, order["user_id"], amount, "topup", {"order_id": order_id})
            await repo.log_event(session, "admin_actions", "info", order["tg_user_id"], order["user_id"], "topup_approved", f"order {order_id}", {"order_id": order_id, "amount": amount})
            await session.commit()

            await bot.send_message(order["chat_id"], f"✅ Баланс пополнен на {amount} ₽.\nТекущий баланс: {new_balance} ₽")
            if call.message and call.message.text:
                await call.message.edit_text("Пополнение подтверждено.")
            elif call.message:
                await call.message.edit_caption("Пополнение подтверждено.")
            await call.answer()
            return

        plan = await repo.load_plan(session, order["plan_id"])
        access_until = None
        if plan:
            access_until = datetime.now(timezone.utc) + timedelta(days=int(plan.get("duration_days") or 0))
        config_uri = await repo.create_vpn_profile_stub(
            session,
            order["user_id"],
            order["meta"].get("protocol"),
            order["meta"].get("server_id"),
            "paid",
            access_until=access_until,
        )
        await repo.log_event(session, "admin_actions", "info", order["tg_user_id"], order["user_id"], "payment_approved", f"order {order_id}", {"order_id": order_id})
        await session.commit()

        await bot.send_message(
            order["chat_id"],
            f"✅ Оплата подтверждена.\nВаш ключ (заглушка):\n{config_uri}",
            reply_markup=instructions_keyboard(),
        )
        if call.message and call.message.text:
            await call.message.edit_text("Оплата подтверждена.")
        elif call.message:
            await call.message.edit_caption("Оплата подтверждена.")
        await call.answer()
        return

    if action == "reject":
        await repo.update_order_status(session, order_id, "failed")
        await repo.log_event(session, "admin_actions", "info", order["tg_user_id"], order["user_id"], "payment_rejected", f"order {order_id}", {"order_id": order_id})
        await session.commit()

        await bot.send_message(order["chat_id"], "Оплата не подтверждена. Если это ошибка — обратитесь в поддержку.")
        if call.message and call.message.text:
            await call.message.edit_text("Оплата отклонена.")
        elif call.message:
            await call.message.edit_caption("Оплата отклонена.")
        await call.answer()
        return

    await call.answer("Неизвестное действие")
