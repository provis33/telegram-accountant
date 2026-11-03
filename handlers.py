"""Telegram commands, photo OCR, and receipt confirmation FSM."""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import tempfile
from datetime import date, datetime, timezone
from html import escape
from io import StringIO
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Settings
from db import CURRENCY, Database
from ocr import OcrError, recognize_text
from parser import parse_amount_token, parse_receipt
from stats import format_last_receipts, format_month_stats

logger = logging.getLogger("accountant")
router = Router()

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
OCR_TEXT_LIMIT = 20_000
HELP_TEXT = (
    "Пришлите фото чека. Я распознаю текст локально, покажу сумму, магазин и дату — "
    "сохранение только после вашей кнопки.\n\n"
    "/stats — текущий месяц\n"
    "/month 2026-11 — конкретный месяц\n"
    "/last — последние 5 чеков\n"
    "/export — CSV за текущий месяц\n"
    "/help — эта инструкция\n\n"
    "Если сумма кривая — нажмите «Исправить сумму» и введите число, например 1234.50."
)


class ReceiptStates(StatesGroup):
    confirming = State()
    waiting_amount = State()


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def current_year_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def preview_keyboard(can_save: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_save:
        builder.button(text="Сохранить", callback_data="rc:save")
    builder.button(text="Исправить сумму", callback_data="rc:fix")
    builder.button(text="Отмена", callback_data="rc:cancel")
    builder.adjust(1)
    return builder.as_markup()


def format_preview(data: dict[str, object]) -> str:
    amount = data.get("amount")
    if isinstance(amount, (int, float)):
        amount_text = f"{float(amount):.2f} {CURRENCY}"
    else:
        amount_text = "не распознана"
    merchant = str(data.get("merchant") or "не распознан")
    receipt_date = str(data.get("receipt_date") or "—")
    return (
        "Распознано:\n"
        f"Сумма: {amount_text}\n"
        f"Магазин: {merchant}\n"
        f"Дата: {receipt_date}\n\n"
        "Проверьте данные перед сохранением."
    )


def parsed_to_fsm(file_id: str, parsed) -> dict[str, object]:
    return {
        "file_id": file_id,
        "ocr_text": (parsed.raw_text or "")[:OCR_TEXT_LIMIT],
        "amount": parsed.amount,
        "merchant": parsed.merchant,
        "receipt_date": parsed.receipt_date.isoformat(),
    }


async def _safe_reply(message: Message, text: str, **kwargs) -> None:
    try:
        await message.answer(text, **kwargs)
    except Exception:
        logger.exception("Failed to reply")


async def send_month_stats(message: Message, db: Database, user_id: int, year_month: str) -> None:
    try:
        count, total = await db.month_summary(user_id, year_month)
        top_rows = await db.top_merchants(user_id, year_month)
        month_rows = await db.month_receipts(user_id, year_month)
    except Exception:
        logger.exception("Failed to load stats for user %s month %s", user_id, year_month)
        await _safe_reply(message, "Не удалось прочитать статистику.")
        return

    top = [
        (str(row["merchant"]), int(row["cnt"]), float(row["total"]))
        for row in top_rows
    ]
    last_slice = list(month_rows)[-5:]
    last_rows = [
        (
            str(row["receipt_date"] or ""),
            str(row["merchant"] or "не распознан"),
            float(row["amount"] or 0),
            str(row["currency"] or CURRENCY),
        )
        for row in last_slice
    ]
    text = format_month_stats(year_month, count, total, top, last_rows)
    await _safe_reply(message, text, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _safe_reply(
        message,
        "Личный бухгалтер: фото чека → локальный OCR → подтверждение → статистика.\n\n"
        "Пришлите фото чека или откройте /help.",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _safe_reply(message, HELP_TEXT)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await send_month_stats(message, db, user_id, current_year_month())


@router.message(Command("month"))
async def cmd_month(message: Message, command: CommandObject, db: Database) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    raw = (command.args or "").strip()
    if not raw or not MONTH_RE.fullmatch(raw):
        await _safe_reply(message, "Формат: /month 2026-11")
        return
    await send_month_stats(message, db, user_id, raw)


@router.message(Command("last"))
async def cmd_last(message: Message, db: Database) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    try:
        rows = await db.last_receipts(user_id, 5)
    except Exception:
        logger.exception("Failed /last for user %s", user_id)
        await _safe_reply(message, "Не удалось прочитать чеки.")
        return
    packed = [
        (
            int(row["id"]),
            str(row["receipt_date"] or ""),
            str(row["merchant"] or "не распознан"),
            float(row["amount"] or 0),
            str(row["currency"] or CURRENCY),
        )
        for row in rows
    ]
    await _safe_reply(message, format_last_receipts(packed), parse_mode="HTML")


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    year_month = current_year_month()
    try:
        rows = await db.month_receipts(user_id, year_month)
    except Exception:
        logger.exception("Failed /export for user %s", user_id)
        await _safe_reply(message, "Не удалось собрать CSV.")
        return
    if not rows:
        await _safe_reply(message, f"За {year_month} чеков нет — экспортировать нечего.")
        return

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "amount", "currency", "merchant", "receipt_date", "created_at"])
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["amount"],
                row["currency"],
                row["merchant"] or "",
                row["receipt_date"] or "",
                row["created_at"] or "",
            ]
        )
    payload = buffer.getvalue().encode("utf-8-sig")
    try:
        await message.answer_document(
            BufferedInputFile(payload, filename=f"receipts_{year_month}.csv"),
            caption=f"Чеки за {escape(year_month)}",
        )
    except Exception:
        logger.exception("Failed to send CSV")
        await _safe_reply(message, "Не удалось отправить файл.")


@router.message(F.document)
async def on_document(message: Message) -> None:
    await _safe_reply(message, "Пришлите чек как фото, не файлом.")


@router.message(F.photo)
async def on_photo(message: Message, state: FSMContext, settings: Settings) -> None:
    user_id = _user_id(message)
    if user_id is None or message.bot is None:
        return
    photo = message.photo[-1]
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    await message.answer("Распознаю чек…")
    try:
        await message.bot.download(photo, destination=tmp_path)
        # RU: OCR — блокирующая операция, поэтому выносим её в отдельный поток.
        # EN: OCR is blocking, so we run it in a separate thread.
        text = await asyncio.to_thread(recognize_text, tmp_path, settings.ocr_lang)
    except OcrError as exc:
        await state.clear()
        await _safe_reply(message, str(exc))
        return
    except Exception:
        logger.exception("Photo processing failed")
        await state.clear()
        await _safe_reply(message, "Не удалось обработать фото. Попробуйте ещё раз.")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    parsed = parse_receipt(text)
    payload = parsed_to_fsm(photo.file_id, parsed)
    await state.update_data(**payload)

    # RU: Без суммы не сохраняем — сразу просим ввести её вручную.
    # EN: Do not save without an amount; ask the user to type it.
    if parsed.amount is None:
        await state.set_state(ReceiptStates.waiting_amount)
        await _safe_reply(
            message,
            format_preview(payload) + "\n\nСумму не распознал. Введите число, например 1234.50",
        )
        return

    await state.set_state(ReceiptStates.confirming)
    await _safe_reply(message, format_preview(payload), reply_markup=preview_keyboard(True))


@router.message(ReceiptStates.waiting_amount, F.text, ~F.text.startswith("/"))
async def on_manual_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount_token(message.text or "")
    if amount is None:
        await _safe_reply(message, "Не понял сумму. Пример: 1234.50 или 1 234,50")
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    await state.set_state(ReceiptStates.confirming)
    await _safe_reply(message, format_preview(data), reply_markup=preview_keyboard(True))


@router.callback_query(F.data == "rc:save")
async def cb_save(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if callback.message is None or callback.from_user is None:
        await callback.answer()
        return
    data = await state.get_data()
    amount = data.get("amount")
    if not isinstance(amount, (int, float)):
        await state.set_state(ReceiptStates.waiting_amount)
        await callback.answer("Нужна сумма", show_alert=True)
        if isinstance(callback.message, Message):
            await callback.message.answer("Введите сумму числом, например 1234.50")
        return

    merchant = data.get("merchant")
    merchant_text = str(merchant) if merchant else None
    try:
        receipt_date = date.fromisoformat(str(data.get("receipt_date")))
    except (TypeError, ValueError):
        receipt_date = datetime.now(timezone.utc).date()

    try:
        receipt_id = await db.insert_receipt(
            user_id=callback.from_user.id,
            file_id=str(data.get("file_id") or "") or None,
            ocr_text=str(data.get("ocr_text") or "") or None,
            amount=float(amount),
            merchant=merchant_text,
            receipt_date=receipt_date,
        )
    except Exception:
        logger.exception("Failed to insert receipt")
        await callback.answer("Ошибка БД", show_alert=True)
        return

    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                f"Чек #{receipt_id} сохранён: {float(amount):.2f} {CURRENCY}."
            )
        except Exception:
            logger.warning("Could not edit preview after save")
    await callback.answer("Сохранено")


@router.callback_query(F.data == "rc:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("Чек не сохранён.")
        except Exception:
            logger.warning("Could not edit preview after cancel")
    await callback.answer("Отменено")


@router.callback_query(F.data == "rc:fix")
async def cb_fix(callback: CallbackQuery, state: FSMContext) -> None:
    # RU: FSM: пользователь сам вводит сумму, если OCR ошибся.
    # EN: FSM: the user types the amount when OCR got it wrong.
    await state.set_state(ReceiptStates.waiting_amount)
    if isinstance(callback.message, Message):
        await callback.message.answer("Введите сумму числом, например 1234.50")
    await callback.answer()
