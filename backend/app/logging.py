"""Local and remote logging for the API process (ASGI + app loggers)."""

from __future__ import annotations

import base64
import copy
import json
import logging
import queue
import re
import sys
import time
import traceback
from datetime import UTC, datetime
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from urllib.request import Request, urlopen

from app.config import settings
from app.observability.context import context_fields
from app.observability.events import EVENT_PAYLOAD_ATTR
from app.observability.sanitize import sanitize_event_payload

FILE_HANDLER_NAME = "opinionssimulator.rotating"
LOGSTASH_HANDLER_NAME = "opinionssimulator.logstash"
LOG_FILE_NAME = "app.log"
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
# Access lines are high volume and stall the single HTTP drain when Logstash is behind.
_REMOTE_SKIP_LOGGERS = frozenset({"uvicorn.access"})
_DROP_REPORT_INTERVAL_SECONDS = 15.0
_ACCESS_TOKEN_RE = re.compile(r"(access_token=)[^&\s\"']+")
_logstash_listener: QueueListener | None = None
_RESERVED_DOCUMENT_KEYS = frozenset({"@timestamp", "message", "log", "process"})


class StructuredLogFormatter(logging.Formatter):
    """JSON lines for structured events; keep the human format otherwise."""

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, EVENT_PAYLOAD_ATTR, None) is not None:
            return json.dumps(log_document_from_record(record), ensure_ascii=False)
        return super().format(record)


def log_document_from_record(record: logging.LogRecord) -> dict[str, object]:
    """Shared local/remote document. Structured extras survive as real fields."""
    payload: dict[str, object] = {
        "@timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
        "message": _redact_message(record.getMessage()),
        "log": {"level": record.levelname.lower(), "logger": record.name},
        "service": settings.log_service.strip(),
        "environment": settings.log_environment.strip(),
        "process": {"pid": record.process, "thread": {"name": record.threadName}},
    }
    extra = getattr(record, EVENT_PAYLOAD_ATTR, None)
    if isinstance(extra, dict):
        for key, value in sanitize_event_payload(extra).items():
            if key in _RESERVED_DOCUMENT_KEYS:
                continue
            payload[key] = value
    stamped = getattr(record, "log_context_fields", None)
    _fill_missing_fields(payload, context_fields() if stamped is None else stamped)
    if record.exc_info:
        exc_type, exc_value, _ = record.exc_info
        payload["error"] = {
            "type": exc_type.__name__ if exc_type else "Exception",
            "message": str(exc_value),
            "stack_trace": "".join(traceback.format_exception(*record.exc_info)),
        }
    return payload


class LocalQueueHandler(QueueHandler):
    """Copy records for the in-process queue without discarding exception data."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return copy.copy(record)


class RemoteDrainFilter(logging.Filter):
    """Keep chatty access logs on the console and rotating file only."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name not in _REMOTE_SKIP_LOGGERS


def _redact_message(message: str) -> str:
    return _ACCESS_TOKEN_RE.sub(r"\1redacted", message)


def _fill_missing_fields(payload: dict[str, object], context: dict[str, object]) -> None:
    """Add correlation ids without overwriting fields already on the record."""
    for key, value in context.items():
        if key in _RESERVED_DOCUMENT_KEYS:
            continue
        current = payload.get(key)
        if key not in payload:
            payload[key] = value
        elif isinstance(current, dict) and isinstance(value, dict):
            for nested_key, nested_value in value.items():
                current.setdefault(nested_key, nested_value)


class LogContextFilter(logging.Filter):
    """Copy the caller's correlation ids onto the record before it is queued.

    The Logstash listener formats documents on another thread, where the
    emitting task's contextvars are no longer visible.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "log_context_fields", None) is None:
            record.log_context_fields = context_fields()
        return True


class LogstashHTTPHandler(logging.Handler):
    """Send one structured JSON document to the authenticated Logstash input."""

    def __init__(self) -> None:
        super().__init__(settings.log_level)
        credentials = (
            f"{settings.logstash_username.strip()}:{settings.logstash_password.get_secret_value()}"
        )
        token = base64.b64encode(credentials.encode()).decode("ascii")
        self.url = settings.logstash_url.strip()
        self.authorization = f"Basic {token}"
        self._dropped_unreported = 0
        self._last_drop_report = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = log_document_from_record(record)
            request = Request(
                self.url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": self.authorization,
                    "Content-Type": "application/json",
                    "User-Agent": "socialism-backend-log-drain/1",
                },
                method="POST",
            )
            with urlopen(request, timeout=settings.logstash_timeout_seconds) as response:
                if response.status >= 300:
                    raise OSError(f"Logstash returned HTTP {response.status}")
        except (OSError, TypeError, ValueError):
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        # Default handleError reprints the originating record. Access logs can
        # include JWTs in the URL, so keep the drop explicit without the payload.
        # A stalled Logstash otherwise prints one line per event.
        now = time.monotonic()
        if now - self._last_drop_report < _DROP_REPORT_INTERVAL_SECONDS:
            self._dropped_unreported += 1
            return
        suppressed = self._dropped_unreported
        self._dropped_unreported = 0
        self._last_drop_report = now
        exc = sys.exc_info()[1]
        kind = type(exc).__name__ if exc is not None else "error"
        detail = str(exc) if exc is not None else ""
        extra = f" ({suppressed} similar drops suppressed)" if suppressed else ""
        sys.stderr.write(
            f"Logstash drain dropped a {record.levelname} record from "
            f"{record.name} ({kind}: {detail}){extra}\n"
        )


def log_file_path() -> Path | None:
    raw = settings.log_dir.strip()
    if not raw:
        return None
    return Path(raw) / LOG_FILE_NAME


def configure_logging() -> Path | None:
    """Attach local and optional queued remote handlers. Console stays with uvicorn.

    Empty ``log_dir`` disables the file. Empty ``logstash_url`` disables the drain.
    Safe to call more than once.
    """
    path = log_file_path()
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    if path is not None and _file_handler() is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        handler.set_name(FILE_HANDLER_NAME)
        handler.setLevel(settings.log_level)
        handler.setFormatter(
            StructuredLogFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        _attach_handler(handler)

    if settings.logstash_url.strip() and _named_handler(LOGSTASH_HANDLER_NAME) is None:
        _attach_logstash_handler()

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


def detach_logstash_logging() -> None:
    """Remove the queued Logstash handler and stop its worker (tests)."""
    global _logstash_listener
    handler = _named_handler(LOGSTASH_HANDLER_NAME)
    if handler is not None:
        _detach_handler(handler)
        handler.close()
    if _logstash_listener is not None:
        _logstash_listener.stop()
        _logstash_listener = None


def _file_handler() -> logging.Handler | None:
    return _named_handler(FILE_HANDLER_NAME)


def _named_handler(name: str) -> logging.Handler | None:
    for handler in logging.getLogger().handlers:
        if handler.get_name() == name:
            return handler
    return None


def _attach_handler(handler: logging.Handler) -> None:
    root = logging.getLogger()
    root.addHandler(handler)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        if uvicorn_logger.propagate and uvicorn_logger is not root:
            continue
        if any(existing.get_name() == handler.get_name() for existing in uvicorn_logger.handlers):
            continue
        uvicorn_logger.addHandler(handler)


def _detach_handler(handler: logging.Handler) -> None:
    root = logging.getLogger()
    if handler in root.handlers:
        root.removeHandler(handler)
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        if handler in uvicorn_logger.handlers:
            uvicorn_logger.removeHandler(handler)


def _attach_logstash_handler() -> None:
    global _logstash_listener
    records: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=settings.logstash_queue_size)
    queue_handler = LocalQueueHandler(records)
    queue_handler.set_name(LOGSTASH_HANDLER_NAME)
    queue_handler.setLevel(settings.log_level)
    queue_handler.addFilter(LogContextFilter())
    queue_handler.addFilter(RemoteDrainFilter())
    _attach_handler(queue_handler)
    _logstash_listener = QueueListener(
        records,
        LogstashHTTPHandler(),
        respect_handler_level=True,
    )
    _logstash_listener.start()
