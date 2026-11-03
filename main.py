"""Telegram personal accountant: polling, handlers, local OCR."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import load_settings
from db import Database
from handlers import router
from ocr import configure_tesseract

logger = logging.getLogger("accountant")


def setup_logging() -> None:
    """Write logs/accountant.log and mirror INFO to stdout."""

    Path("logs").mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not any(isinstance(handler, logging.FileHandler) for handler in root.handlers):
        file_handler = logging.FileHandler("logs/accountant.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    logging.getLogger("aiogram").setLevel(logging.INFO)


async def run() -> None:
    setup_logging()
    settings = load_settings()
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    db = Database(settings.db_path)

    dp["settings"] = settings
    dp["db"] = db
    dp.include_router(router)

    async def on_startup() -> None:
        await db.connect()
        configure_tesseract(settings.tesseract_cmd)
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Приветствие"),
                BotCommand(command="help", description="Инструкция"),
                BotCommand(command="stats", description="Статистика за текущий месяц"),
                BotCommand(command="month", description="Статистика: /month 2026-11"),
                BotCommand(command="last", description="Последние 5 чеков"),
                BotCommand(command="export", description="CSV за текущий месяц"),
            ]
        )
        logger.info("Startup complete, ocr_lang=%s", settings.ocr_lang)

    async def on_shutdown() -> None:
        await db.close()
        logger.info("Shutdown complete")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by keyboard")


if __name__ == "__main__":
    main()
