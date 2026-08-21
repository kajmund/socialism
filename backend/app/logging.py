"""Rotating file log for the API process (ASGI + app loggers)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

FILE_HANDLER_NAME = "opinionssimulator.rotating"
LOG_FILE_NAME = "app.log"
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def log_file_path() -> Path | None:
    raw = settings.log_dir.strip()
    if not raw:
        return None
    return Path(raw) / LOG_FILE_NAME


def configure_logging() -> Path | None:
    """Attach one rotating file handler. Console stays with uvicorn.

    Empty ``log_dir`` disables the file. Safe to call more than once.
    """
    path = log_file_path()
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if _file_handler() is not None:
        return path

    handler = RotatingFileHandler(
        path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.set_name(FILE_HANDLER_NAME)
    handler.setLevel(settings.log_level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    for name in _UVICORN_LOGGERS:
        uv = logging.getLogger(name)
        if uv.propagate and uv is not root:
            continue
        if any(h.get_name() == FILE_HANDLER_NAME for h in uv.handlers):
            continue
        uv.addHandler(handler)
    return path


def detach_file_logging() -> None:
    """Remove our rotating handler (tests)."""
    handler = _file_handler()
    if handler is None:
        return
    root = logging.getLogger()
    if handler in root.handlers:
        root.removeHandler(handler)
    for name in _UVICORN_LOGGERS:
        uv = logging.getLogger(name)
        if handler in uv.handlers:
            uv.removeHandler(handler)
    handler.close()


def _file_handler() -> logging.Handler | None:
    for handler in logging.getLogger().handlers:
        if handler.get_name() == FILE_HANDLER_NAME:
            return handler
    return None
