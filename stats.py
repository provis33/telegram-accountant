"""Monthly summaries as monospaced tables for Telegram HTML <pre>."""

from __future__ import annotations

from html import escape

from tabulate import tabulate

from db import CURRENCY


def wrap_pre(table: str) -> str:
    return f"<pre>{escape(table)}</pre>"


def format_money(amount: float, currency: str = CURRENCY) -> str:
    return f"{amount:,.2f} {currency}".replace(",", " ")


def format_month_stats(
    year_month: str,
    count: int,
    total: float,
    top_merchants: list[tuple[str, int, float]],
    last_rows: list[tuple[str, str, float, str]],
) -> str:
    if count == 0:
        return f"За {year_month} чеков нет. Пришлите фото чека."

    avg = total / count if count else 0.0
    summary = tabulate(
        [
            ["Месяц", year_month],
            ["Чеков", str(count)],
            ["Сумма", format_money(total)],
            ["Средний чек", format_money(avg)],
        ],
        tablefmt="simple",
    )

    parts = [f"Статистика за {year_month}", wrap_pre(summary)]

    if top_merchants:
        merchant_table = tabulate(
            [
                [name[:24], cnt, format_money(amount)]
                for name, cnt, amount in top_merchants
            ],
            headers=["Магазин", "N", "Сумма"],
            tablefmt="simple",
        )
        parts.append("Топ магазинов")
        parts.append(wrap_pre(merchant_table))

    if last_rows:
        last_table = tabulate(
            [
                [day, name[:20], format_money(amount, currency)]
                for day, name, amount, currency in last_rows
            ],
            headers=["Дата", "Магазин", "Сумма"],
            tablefmt="simple",
        )
        parts.append("Последние чеки")
        parts.append(wrap_pre(last_table))

    return "\n".join(parts)


def format_last_receipts(rows: list[tuple[int, str, str, float, str]]) -> str:
    if not rows:
        return "Чеков пока нет. Пришлите фото."
    table = tabulate(
        [
            [receipt_id, day, name[:22], format_money(amount, currency)]
            for receipt_id, day, name, amount, currency in rows
        ],
        headers=["ID", "Дата", "Магазин", "Сумма"],
        tablefmt="simple",
    )
    return "Последние чеки\n" + wrap_pre(table)
