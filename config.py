"""Load settings from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_DB_PATH = "data/accountant.db"
DEFAULT_OCR_LANG = "rus+eng"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Secrets stay in env vars, never in code."""

    telegram_bot_token: str
    db_path: str
    tesseract_cmd: str
    ocr_lang: str


def load_settings() -> Settings:
    """Read `.env`. Empty TELEGRAM_BOT_TOKEN stops the process."""

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is empty. Copy .env.example to .env and paste the bot token."
        )
    return Settings(
        telegram_bot_token=token,
        db_path=os.getenv("DB_PATH", "").strip() or DEFAULT_DB_PATH,
        tesseract_cmd=os.getenv("TESSERACT_CMD", "").strip(),
        ocr_lang=os.getenv("OCR_LANG", "").strip() or DEFAULT_OCR_LANG,
    )
