"""Per-körning file logs — one file per attempt variant under data/oasis/."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

ARTIFACT_ROOT = Path("data/oasis")

_LOG_SEGMENT = re.compile(r"^[a-zA-Z0-9_-]+$")
_DEFAULT_TAIL_LINES = 200
_MAX_TAIL_LINES = 500
_MAX_TAIL_BYTES = 256_000

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


def validate_log_segment(name: str, value: str) -> str:
    if not _LOG_SEGMENT.fullmatch(value):
        raise ValueError(f"Invalid {name}: must be alphanumeric with _ or -")
    return value


def resolve_run_log_path(run_id: int, attempt_id: str, variant_id: str) -> Path:
    validate_log_segment("attempt_id", attempt_id)
    validate_log_segment("variant_id", variant_id)
    path = run_variant_log_path(run_id, attempt_id, variant_id).resolve()
    root = ARTIFACT_ROOT.resolve()
    if root not in path.parents and path != root:
        raise ValueError("Log path escapes artifact root")
    return path


def tail_run_log_file(
    path: Path,
    *,
    lines: int = _DEFAULT_TAIL_LINES,
    max_bytes: int = _MAX_TAIL_BYTES,
) -> tuple[str, bool]:
    """Return the last ``lines`` of a log file and whether the read was byte-truncated."""
    if lines < 1:
        raise ValueError("lines must be >= 1")
    if not path.is_file():
        raise FileNotFoundError(str(path))

    size = path.stat().st_size
    truncated = size > max_bytes
    if truncated:
        with path.open("rb") as fh:
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read()
        text = chunk.decode("utf-8", errors="replace")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    all_lines = text.splitlines()
    if len(all_lines) <= lines:
        return "\n".join(all_lines), truncated
    return "\n".join(all_lines[-lines:]), truncated


def read_run_log_tail(
    *,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    lines: int = _DEFAULT_TAIL_LINES,
) -> tuple[Path, str, bool]:
    if lines < 1 or lines > _MAX_TAIL_LINES:
        raise ValueError(f"lines must be between 1 and {_MAX_TAIL_LINES}")
    path = resolve_run_log_path(run_id, attempt_id, variant_id)
    content, truncated = tail_run_log_file(path, lines=lines)
    return path, content, truncated


__all__ = [
    "ARTIFACT_ROOT",
    "_MAX_TAIL_LINES",
    "capture_run_log",
    "ensure_run_log_handler",
    "read_run_log_tail",
    "resolve_run_log_path",
    "run_attempt_log_dir",
    "run_variant_log_path",
    "tail_run_log_file",
    "validate_log_segment",
    "write_run_log_note",
]
