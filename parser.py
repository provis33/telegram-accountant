"""Extract amount, date, and merchant from raw OCR text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from db import CURRENCY

LABEL_RE = re.compile(
    r"(итог(?:о|а)?|к\s*оплате|сумма|total|amount|grand\s*total|списано)",
    re.IGNORECASE,
)
AMOUNT_TOKEN_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d+[.,]\d{1,2}|\d{1,8})(?!\d)"
)
DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
SKIP_MERCHANT_RE = re.compile(
    r"(итог|оплат|сумма|total|касс|чек|фн|фд|фп|инн|огрн|nds|ндс|www\.|http)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedReceipt:
    amount: float | None
    currency: str
    merchant: str | None
    receipt_date: date
    raw_text: str


def parse_amount_token(token: str) -> float | None:
    """Parse a human amount like '1 234,50' into a float."""

    cleaned = token.replace("\u00a0", " ").replace(" ", "").strip()
    if not cleaned:
        return None
    if cleaned.count(",") == 1 and cleaned.count(".") == 0:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    elif cleaned.count(",") > 1:
        parts = cleaned.split(",")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value <= 0 or value > 10_000_000:
        return None
    return round(value, 2)


def _looks_like_year(value: float) -> bool:
    return value.is_integer() and 1900 <= value <= 2099


def _amounts_in(text: str) -> list[float]:
    found: list[float] = []
    for match in AMOUNT_TOKEN_RE.finditer(text):
        value = parse_amount_token(match.group(1))
        if value is None or _looks_like_year(value):
            continue
        found.append(value)
    return found


def extract_amount(text: str) -> float | None:
    """Prefer a number near TOTAL/ИТОГО; otherwise the largest plausible amount.

    # RU: Если метки «ИТОГО» нет — берём максимальное число, похожее на сумму.
    # EN: If there is no TOTAL label, fall back to the largest amount-like number.
    """

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not LABEL_RE.search(line):
            continue
        window = line
        if index + 1 < len(lines):
            window = f"{line} {lines[index + 1]}"
        labeled = _amounts_in(window)
        if labeled:
            return max(labeled)

    candidates = _amounts_in(text)
    if not candidates:
        return None
    with_cents = [value for value in candidates if not value.is_integer()]
    pool = with_cents or [value for value in candidates if value >= 10]
    if not pool:
        return None
    return max(pool)


def extract_date(text: str) -> date | None:
    for match in DATE_RE.finditer(text):
        day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue
        if date(2000, 1, 1) <= parsed <= date(2100, 1, 1):
            return parsed
    return None


def extract_merchant(text: str) -> str | None:
    """First substantial line that does not look like a total/date/inn."""

    for raw in text.splitlines():
        line = " ".join(raw.split()).strip(" .-•*")
        if len(line) < 3:
            continue
        if DATE_RE.search(line) or LABEL_RE.search(line) or SKIP_MERCHANT_RE.search(line):
            continue
        if _amounts_in(line) and len(line) < 24:
            continue
        return line[:80]
    return None


def parse_receipt(text: str) -> ParsedReceipt:
    """Turn OCR text into structured fields. Missing amount stays None."""

    today = datetime.now(timezone.utc).date()
    return ParsedReceipt(
        amount=extract_amount(text),
        currency=CURRENCY,
        merchant=extract_merchant(text),
        receipt_date=extract_date(text) or today,
        raw_text=text,
    )
