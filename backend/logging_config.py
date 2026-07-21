"""Configuration centralisée du logging de l'application."""

import os
from logging.config import dictConfig


def configure_logging() -> None:
    """Configure les handlers et le niveau de logs de l'application."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", os.path.join("logs", "app.log"))
    log_dir = os.path.dirname(log_file)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": log_level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": log_level,
                    "filename": log_file,
                    "maxBytes": 1_000_000,
                    "backupCount": 5,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": log_level,
            },
        }
    )
