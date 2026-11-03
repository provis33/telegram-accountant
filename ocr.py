"""Local Tesseract OCR. No cloud APIs."""

from __future__ import annotations

import logging
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

logger = logging.getLogger("accountant")

MIN_SIDE = 800
MAX_SIDE = 2000


class OcrError(Exception):
    """Raised when Tesseract is missing or returns nothing useful."""


def configure_tesseract(tesseract_cmd: str) -> None:
    """Use a custom binary path when TESSERACT_CMD is set; otherwise PATH."""

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def preprocess_image(path: str) -> str:
    """Grayscale, autocontrast, resize so thin receipt text is readable."""

    image = Image.open(path)
    try:
        transposed = ImageOps.exif_transpose(image)
        if transposed is not None:
            image = transposed
    except Exception:
        logger.debug("EXIF transpose skipped for %s", path)
    image = image.convert("L")
    image = ImageOps.autocontrast(image)

    width, height = image.size
    min_side = min(width, height)
    max_side = max(width, height)
    if min_side < MIN_SIDE:
        scale = MIN_SIDE / min_side
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
        width, height = image.size
        max_side = max(width, height)
    if max_side > MAX_SIDE:
        scale = MAX_SIDE / max_side
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    image.save(path)
    return path


def recognize_text(path: str, lang: str) -> str:
    """Blocking OCR. Call from asyncio.to_thread."""

    # RU: OCR — блокирующая операция, поэтому выносим её в отдельный поток.
    # EN: OCR is blocking, so we run it in a separate thread.
    preprocess_image(path)
    try:
        text = pytesseract.image_to_string(Image.open(path), lang=lang)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrError(
            "Tesseract не найден. Установите его и при необходимости задайте TESSERACT_CMD."
        ) from exc
    except pytesseract.TesseractError as exc:
        logger.error("Tesseract failed: %s", exc)
        raise OcrError("Tesseract не смог прочитать изображение.") from exc

    cleaned = (text or "").strip()
    if not cleaned:
        raise OcrError("На фото не удалось распознать текст. Пришлите более чёткий снимок.")
    return cleaned
