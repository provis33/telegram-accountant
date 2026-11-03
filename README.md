# telegram-accountant
Telegram bot that OCRs receipts locally, saves them to SQLite, and shows monthly spend tables | Telegram-бот: локальный OCR чеков, SQLite и таблицы трат за месяц

## Что умеет

- Принимает **фото** чека, берёт самый большой размер
- Распознаёт текст локально (`rus+eng`)
- Достаёт сумму, дату и магазин
- Показывает превью с кнопками «Сохранить», «Отмена», «Исправить сумму»
- Без суммы в БД ничего не пишет просит ввести число вручную
- `/stats`, `/month YYYY-MM`, `/last`, `/export`

## Требования

- Python 3.11+
- Токен у [@BotFather](https://t.me/BotFather)
- **Tesseract OCR** и русский language pack (это отдельная программа, не pip-пакет)

## Установка Python-зависимостей

```bash
cd telegram-accountant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Linux/macOS: `source .venv/bin/activate` и `cp .env.example .env`.

В `.env` вставьте `TELEGRAM_BOT_TOKEN`. **Не коммитьте `.env`.** Если токен пустой то бот не стартанёт.

## Tesseract

### Windows

1. Установщик: [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki).
2. При установке отметьте Additional language data → **Russian**.
3. Типичный путь: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
4. Если команда `tesseract` не находится в PATH, пропишите путь в `.env`:

```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### Linux

```bash
sudo apt install tesseract-ocr tesseract-ocr-rus
```

`TESSERACT_CMD` можно оставить пустым.

### macOS

```bash
brew install tesseract tesseract-lang
```

Без Tesseract бот **запускается**, но фото чека не распознает и напишет, что бинарник не найден.

## Запуск

```bash
python main.py
```

Логи: `logs/accountant.log`. База: `data/accountant.db` (создаётся сама).

## Команды

| Команда | Что делает |
| --- | --- |
| `/start` | Приветствие |
| `/help` | Инструкция |
| `/stats` | Сумма, средний чек, топ-5 магазинов, последние чеки за текущий месяц |
| `/month 2026-11` | То же за выбранный месяц |
| `/last` | Последние 5 чеков |
| `/export` | CSV текущего месяца |

Чек присылайте **фотографией**, не документом.

## Как разбирается чек

1. Grayscale + autocontrast, при необходимости resize.
2. `pytesseract` в `asyncio.to_thread`, язык `OCR_LANG` (по умолчанию `rus+eng`).
3. Сумма: строки с «ИТОГО», «К ОПЛАТЕ», «СУММА», «TOTAL», затем число. Если метки нет самое большое число, похожее на сумму (годы вроде 2024 отбрасываются).
4. Дата: `dd.mm.yyyy`, `dd/mm/yyyy`, `dd-mm-yyyy`. Если нет - сегодня (UTC).
5. Магазин: первая содержательная строка. Если нет - пусто.
6. Валюта всегда `RUB`.
7. Запись в SQLite только после «Сохранить». Сырой OCR-текст хранится для отладки.

## Ограничения

- OCR ошибается на мятых, тёмных, сильно сжатых чеках.
- Сумму часто нужно поправить кнопкой «Исправить сумму».
- Магазин и дата - эвристики, не кассовый ФФД.
- Документ-файлы (PDF, несжатый JPEG как file) не принимаются — только photo.
- FSM в памяти: после рестарта бота неподтверждённый чек пропадает.
- Таблицы в Telegram - моноширинный `<pre>` через `tabulate`.

## Ручная проверка

1. Заполните токен, поставьте Tesseract, запустите бота.
2. Пришлите фото чека придёт превью полей.
3. «Сохранить» запись в базе, `/last` показывает чек.
4. Новый чек → «Исправить сумму» → `1234.50` → сохранить.
5. Чек без читаемой суммы бот просит число, кнопка сохранения не предлагается.
6. `/stats` и `/month 2026-11` - таблицы. `/export` - CSV.
7. В репозитории нет секретов, только пустой `.env.example`.
