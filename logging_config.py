"""
Centralized logging configuration for Alpha Signals MAS.

ARCHITECTURE NOTE:
-----------------
This module is imported once at startup by run.py.
All agent modules then call `logging.getLogger(__name__)`
to receive a child logger that inherits this configuration.

Do NOT call logging.basicConfig() anywhere else in the codebase.
Calling it multiple times produces duplicate log entries.

The TelegramAlertHandler only fires at ERROR level and above —
it will not spam your channel with INFO or DEBUG messages.
"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
LOG_FILE_PATH: str = "logs/mas_pipeline.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024   
LOG_BACKUP_COUNT: int = 3              


class TelegramAlertHandler(logging.Handler):
    """
    Custom logging.Handler that sends ERROR and CRITICAL log records
    to the configured Telegram channel.

    Fires only for ERROR and above — INFO/DEBUG messages are silently
    ignored by this handler's level filter.

    Uses asyncio.run() to fire the async Telegram call synchronously
    from within the logging system's synchronous emit() method.
    If the Telegram send itself fails, we silently suppress the error
    to prevent a logging failure from crashing the main process.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
            return

        try:
            log_entry = self.format(record)
            message = (
                f"ALPHA SIGNALS MAS — PIPELINE ALERT\n\n"
                f"Level    : {record.levelname}\n"
                f"Module   : {record.name}\n"
                f"Function : {record.funcName}\n"
                f"Line     : {record.lineno}\n\n"
                f"Message  :\n{log_entry}"
            )
            
            message = message[:4090]
            asyncio.run(self._send_alert(message))
        except Exception:
            self.handleError(record)

    async def _send_alert(self, message: str) -> None:
        try:
            from telegram import Bot
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            async with bot:
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=message,
                    parse_mode=None,
                )
        except Exception:
            pass


def configure_logging(level: int = logging.INFO) -> None:
    """
    Initialize the root logger with three handlers:
        1. RotatingFileHandler  → logs/mas_pipeline.log
        2. StreamHandler        → stdout (terminal / docker logs)
        3. TelegramAlertHandler → Telegram channel (ERROR+ only)

    Call this function ONCE at the top of run.py before importing
    any agent modules. All subsequent getLogger() calls will
    automatically inherit this configuration.
    """
    os.makedirs("logs", exist_ok=True)

    log_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        filename=LOG_FILE_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(log_format)
    root_logger.addHandler(stream_handler)

    telegram_handler = TelegramAlertHandler()
    telegram_handler.setLevel(logging.ERROR)
    telegram_handler.setFormatter(log_format)
    root_logger.addHandler(telegram_handler)

    logging.getLogger("fontTools").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.info("Logging system initialized. File: %s", LOG_FILE_PATH)