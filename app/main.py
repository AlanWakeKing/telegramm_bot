import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .handlers import menu, buy, payment, config, balance, profile, fallback


dp = Dispatcher(storage=MemoryStorage())


def register_middlewares(dp: Dispatcher):
    @dp.update.middleware()
    async def db_session_middleware(handler, event, data):
        async with SessionLocal() as session:  # type: AsyncSession
            data["session"] = session
            return await handler(event, data)


def register_handlers(dp: Dispatcher):
    dp.include_router(menu.router)
    dp.include_router(buy.router)
    dp.include_router(payment.router)
    dp.include_router(config.router)
    dp.include_router(balance.router)
    dp.include_router(profile.router)
    dp.include_router(fallback.router)


async def main():
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    register_middlewares(dp)
    register_handlers(dp)

    await bot.set_my_commands([
        BotCommand(command="start", description="Меню"),
    ])

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
