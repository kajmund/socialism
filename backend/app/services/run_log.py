"""Per-körning file logs — one file per attempt variant under data/oasis/."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

ARTIFACT_ROOT = Path("data/oasis")

_log_file: ContextVar[Path | None] = ContextVar("run_log_file", default=None)
_handler_lock = threading.Lock()
_handler_installed = False

# Loggers that produce useful körning noise (CAMEL / OASIS / our services).
_RUN_LOGGER_NAMES = (
    "camel",
    "oasis",
    "social",
    "social.agent",
    "oasis.env",
    "app.services",
)


class _ContextFileHandler(logging.Handler):
    """Writes records to the path in the current ContextVar (task-local)."""

    def emit(self, record: logging.LogRecord) -> None:
        path = _log_file.get()
        if path is None:
            return
        try:
            msg = self.format(record)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:  # noqa: BLE001 — logging must not break the sim
            self.handleError(record)


def ensure_run_log_handler() -> None:
    """Install a single root handler that fans out via ContextVar."""
    global _handler_installed
    with _handler_lock:
        if _handler_installed:
            return
        handler = _ContextFileHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root = logging.getLogger()
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        root.addHandler(handler)
        for name in _RUN_LOGGER_NAMES:
            lg = logging.getLogger(name)
            if lg.level == logging.NOTSET or lg.level > logging.INFO:
                lg.setLevel(logging.INFO)
            lg.propagate = True
        _handler_installed = True


def run_attempt_log_dir(run_id: int, attempt_id: str) -> Path:
    return ARTIFACT_ROOT / f"run_{run_id}" / "attempts" / attempt_id


def run_variant_log_path(run_id: int, attempt_id: str, variant_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in variant_id)
    return run_attempt_log_dir(run_id, attempt_id) / f"{safe}.log"


def write_run_log_note(path: Path, message: str) -> Path:
    """Create/overwrite a short log file (e.g. engine=none or preflight failure)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(message.rstrip() + "\n", encoding="utf-8")
    return path


@contextmanager
def capture_run_log(path: Path) -> Iterator[Path]:
    """Capture logging from this asyncio task into ``path`` until exit."""
    ensure_run_log_handler()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    token = _log_file.set(path)
    log = logging.getLogger("app.services.run_log")
    try:
        log.info("Run log started → %s", path)
        yield path
        log.info("Run log finished → %s", path)
    finally:
        _log_file.reset(token)


__all__ = [
    "ARTIFACT_ROOT",
    "capture_run_log",
    "ensure_run_log_handler",
    "run_attempt_log_dir",
    "run_variant_log_path",
    "write_run_log_note",
]
