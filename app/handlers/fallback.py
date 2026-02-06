
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()


@router.callback_query(F.data == "help:stub")
async def help_stub(call: CallbackQuery):
    await call.message.answer("❓ Инструкции скоро будут добавлены.")
    await call.answer()


@router.callback_query(F.data == "nav:menu")
async def nav_menu(call: CallbackQuery, session: AsyncSession):
    from .menu import render_menu
    from ..services import repo
    u = await repo.load_user_with_session(session, call.from_user.id)
    if not u:
        await call.answer()
        return
    await render_menu(call.message, session, u.get("role", "user"))
    await call.answer()


@router.message(F.text)
async def unknown(message: Message):
    await message.answer("Команда не распознана. Откройте меню: /start")
