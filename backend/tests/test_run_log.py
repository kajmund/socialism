"""Per-körning file log capture."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.services.run_log import (
    capture_run_log,
    run_variant_log_path,
    write_run_log_note,
)


def test_write_run_log_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = run_variant_log_path(7, "att_abc", "main")
    write_run_log_note(path, "engine=none\nstatus=empty_attempt")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "engine=none" in text
    assert text.endswith("\n")


def test_capture_run_log_writes_logger_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Path("data/oasis/run_1/attempts/att_x/main.log")
    with capture_run_log(path):
        logging.getLogger("app.services.oasis_run").info("hello from sim")
        logging.getLogger("camel.memories").warning("truncation demo")
    text = path.read_text(encoding="utf-8")
    assert "Run log started" in text
    assert "hello from sim" in text
    assert "truncation demo" in text
    assert "Run log finished" in text


async def _task_write(path: Path, message: str) -> str:
    with capture_run_log(path):
        logging.getLogger("app.services").info(message)
        await asyncio.sleep(0.01)
    return path.read_text(encoding="utf-8")


def test_capture_run_log_isolates_concurrent_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = Path("data/oasis/run_1/attempts/att_x/a.log")
    b = Path("data/oasis/run_1/attempts/att_x/b.log")

    async def run() -> None:
        ta, tb = await asyncio.gather(
            _task_write(a, "variant-a-only"),
            _task_write(b, "variant-b-only"),
        )
        assert "variant-a-only" in ta
        assert "variant-b-only" not in ta
        assert "variant-b-only" in tb
        assert "variant-a-only" not in tb

    asyncio.run(run())
