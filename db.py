"""SQLite storage for confirmed receipts."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger("accountant")

CURRENCY = "RUB"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


class Database:
    """Thin aiosqlite wrapper. One connection for the bot process."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not connected")
        return self._db

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.init_db()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def init_db(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_id TEXT,
                ocr_text TEXT,
                amount REAL,
                currency TEXT NOT NULL DEFAULT 'RUB',
                merchant TEXT,
                receipt_date TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_user_date
                ON receipts (user_id, receipt_date);
            """
        )
        await self.conn.commit()

    async def insert_receipt(
        self,
        *,
        user_id: int,
        file_id: str | None,
        ocr_text: str | None,
        amount: float,
        merchant: str | None,
        receipt_date: date,
        currency: str = CURRENCY,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO receipts (
                user_id, file_id, ocr_text, amount, currency, merchant, receipt_date, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                file_id,
                ocr_text,
                amount,
                currency,
                merchant,
                receipt_date.isoformat(),
                to_iso(utc_now()),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def last_receipts(self, user_id: int, limit: int = 5) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT id, amount, currency, merchant, receipt_date, created_at
            FROM receipts
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return list(await cursor.fetchall())

    async def month_receipts(self, user_id: int, year_month: str) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT id, amount, currency, merchant, receipt_date, created_at
            FROM receipts
            WHERE user_id = ? AND receipt_date LIKE ?
            ORDER BY receipt_date ASC, id ASC
            """,
            (user_id, f"{year_month}%"),
        )
        return list(await cursor.fetchall())

    async def month_summary(self, user_id: int, year_month: str) -> tuple[int, float]:
        cursor = await self.conn.execute(
            """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
            FROM receipts
            WHERE user_id = ? AND receipt_date LIKE ? AND amount IS NOT NULL
            """,
            (user_id, f"{year_month}%"),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0, 0.0
        return int(row["cnt"]), float(row["total"])

    async def top_merchants(
        self,
        user_id: int,
        year_month: str,
        limit: int = 5,
    ) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(
            """
            SELECT COALESCE(merchant, 'не распознан') AS merchant,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(amount), 0) AS total
            FROM receipts
            WHERE user_id = ? AND receipt_date LIKE ? AND amount IS NOT NULL
            GROUP BY COALESCE(merchant, 'не распознан')
            ORDER BY total DESC, cnt DESC
            LIMIT ?
            """,
            (user_id, f"{year_month}%", limit),
        )
        return list(await cursor.fetchall())
