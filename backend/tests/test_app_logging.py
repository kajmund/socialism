"""Rotating API process log."""

from __future__ import annotations

import logging

from app.logging import configure_logging, detach_file_logging, log_file_path


def test_configure_logging_disabled_when_log_dir_empty(monkeypatch):
    monkeypatch.setattr("app.logging.settings.log_dir", "")
    assert log_file_path() is None
    assert configure_logging() is None


def test_configure_logging_writes_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.logging.settings.log_dir", str(tmp_path))
    monkeypatch.setattr("app.logging.settings.log_level", "INFO")
    monkeypatch.setattr("app.logging.settings.log_max_bytes", 2_000_000)
    monkeypatch.setattr("app.logging.settings.log_backup_count", 3)
    try:
        path = configure_logging()
        assert path == tmp_path / "app.log"
        assert configure_logging() == path
        file_handlers = [
            h
            for h in logging.getLogger().handlers
            if h.get_name() == "opinionssimulator.rotating"
        ]
        assert len(file_handlers) == 1
        logging.getLogger("app.tests.logging").error("deepseek boom")
        for handler in file_handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
        assert "deepseek boom" in text
    finally:
        detach_file_logging()


def test_configure_logging_rolls_over(tmp_path, monkeypatch):
    monkeypatch.setattr("app.logging.settings.log_dir", str(tmp_path))
    monkeypatch.setattr("app.logging.settings.log_level", "INFO")
    monkeypatch.setattr("app.logging.settings.log_max_bytes", 1024)
    monkeypatch.setattr("app.logging.settings.log_backup_count", 2)
    try:
        path = configure_logging()
        assert path is not None
        log = logging.getLogger("app.tests.logging.roll")
        for _ in range(40):
            log.info("x" * 80)
        for handler in logging.getLogger().handlers:
            if handler.get_name() == "opinionssimulator.rotating":
                handler.flush()
        assert path.is_file()
        assert (tmp_path / "app.log.1").is_file()
    finally:
        detach_file_logging()
