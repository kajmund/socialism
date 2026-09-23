"""Rotating API process log."""

from __future__ import annotations

import logging
import sys
import threading
from json import loads

from pydantic import SecretStr

from app.config import settings
from app.logging import (
    LogstashHTTPHandler,
    configure_logging,
    detach_file_logging,
    detach_logstash_logging,
    log_file_path,
)
from app.observability.context import log_context
from app.observability.events import log_event


def test_configure_logging_disabled_when_log_dir_empty(monkeypatch):
    monkeypatch.setattr("app.logging.settings.log_dir", "")
    monkeypatch.setattr("app.logging.settings.logstash_url", "")
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


def test_logstash_handler_posts_ecs_json(monkeypatch):
    monkeypatch.setattr("app.logging.settings.logstash_url", "https://logs.example.test")
    monkeypatch.setattr("app.logging.settings.logstash_username", "socialism")
    monkeypatch.setattr("app.logging.settings.logstash_password", SecretStr("secret-password"))
    monkeypatch.setattr("app.logging.settings.log_service", "socialism-backend")
    monkeypatch.setattr("app.logging.settings.log_environment", "test")
    sent = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, *, timeout):
        sent["request"] = request
        sent["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.logging.urlopen", fake_urlopen)
    handler = LogstashHTTPHandler()
    record = logging.LogRecord(
        "app.tests.remote", logging.ERROR, __file__, 1, "något gick %s", ("fel",), None
    )

    handler.emit(record)

    request = sent["request"]
    assert request.full_url == "https://logs.example.test"
    assert request.get_header("Authorization").startswith("Basic ")
    assert b'"message": "n\\u00e5got gick fel"' not in request.data
    assert "något gick fel" in request.data.decode("utf-8")
    assert '"service": "socialism-backend"' in request.data.decode("utf-8")
    assert '"environment": "test"' in request.data.decode("utf-8")
    assert sent["timeout"] == settings.logstash_timeout_seconds


def test_logstash_handler_timeout_does_not_print_record_message(monkeypatch, capsys):
    monkeypatch.setattr("app.logging.settings.logstash_url", "https://logs.example.test")
    monkeypatch.setattr("app.logging.settings.logstash_username", "socialism")
    monkeypatch.setattr("app.logging.settings.logstash_password", SecretStr("secret"))

    def fake_urlopen(_request, *, timeout):
        del timeout
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr("app.logging.urlopen", fake_urlopen)
    handler = LogstashHTTPHandler()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:1", "/ws/jobs?access_token=secret-token"),
        None,
    )
    handler.emit(record)
    err = capsys.readouterr().err
    assert "Logstash drain dropped" in err
    assert "TimeoutError" in err
    assert "secret-token" not in err
    assert "access_token" not in err


def test_logstash_handler_includes_structured_event_fields(monkeypatch):
    monkeypatch.setattr("app.logging.settings.logstash_url", "https://logs.example.test")
    monkeypatch.setattr("app.logging.settings.logstash_username", "socialism")
    monkeypatch.setattr("app.logging.settings.logstash_password", SecretStr("secret"))
    sent = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, *, timeout):
        sent["payload"] = loads(request.data)
        return Response()

    monkeypatch.setattr("app.logging.urlopen", fake_urlopen)
    handler = LogstashHTTPHandler()
    logger = logging.getLogger("app.tests.research.events")
    previous_handlers = list(logger.handlers)
    previous_propagate = logger.propagate
    logger.handlers = [handler]
    logger.propagate = False
    try:
        with log_context(run_id="run-1", attempt_id="att-1", module="dd", ensure_trace_id=True):
            log_event(
                logger,
                "research.jev.assessment.completed",
                dataset="socialism.research",
                outcome="success",
                duration_ms=12.5,
                fields={"jev": {"decision": "sufficient", "answerable_now_probability": 0.96}},
            )
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagate

    payload = sent["payload"]
    assert payload["event"]["name"] == "research.jev.assessment.completed"
    assert payload["event"]["dataset"] == "socialism.research"
    assert payload["jev"]["decision"] == "sufficient"
    assert payload["jev"]["answerable_now_probability"] == 0.96
    assert payload["run"]["id"] == "run-1"
    assert payload["attempt"]["id"] == "att-1"
    assert payload["research"]["module"] == "dd"
    assert payload["trace"]["id"]


def test_logstash_handler_includes_exception(monkeypatch):
    monkeypatch.setattr("app.logging.settings.logstash_url", "https://logs.example.test")
    monkeypatch.setattr("app.logging.settings.logstash_username", "socialism")
    monkeypatch.setattr("app.logging.settings.logstash_password", SecretStr("secret"))
    sent = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, *, timeout):
        sent["payload"] = loads(request.data)
        return Response()

    monkeypatch.setattr("app.logging.urlopen", fake_urlopen)
    handler = LogstashHTTPHandler()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.getLogger("app.tests.remote").makeRecord(
            "app.tests.remote",
            logging.ERROR,
            __file__,
            1,
            "failed",
            (),
            sys.exc_info(),
        )

    handler.emit(record)

    assert sent["payload"]["error"]["type"] == "RuntimeError"
    assert "RuntimeError: boom" in sent["payload"]["error"]["stack_trace"]


def test_configure_logstash_is_queued_and_idempotent(monkeypatch):
    monkeypatch.setattr("app.logging.settings.log_dir", "")
    monkeypatch.setattr("app.logging.settings.logstash_url", "https://logs.example.test")
    monkeypatch.setattr("app.logging.settings.logstash_username", "socialism")
    monkeypatch.setattr("app.logging.settings.logstash_password", SecretStr("secret"))
    monkeypatch.setattr("app.logging.settings.logstash_queue_size", 10)
    delivered = threading.Event()

    def fake_emit(_self, _record):
        delivered.set()

    monkeypatch.setattr(LogstashHTTPHandler, "emit", fake_emit)
    try:
        assert configure_logging() is None
        assert configure_logging() is None
        handlers = [
            handler
            for handler in logging.getLogger().handlers
            if handler.get_name() == "opinionssimulator.logstash"
        ]
        assert len(handlers) == 1
        logging.getLogger("app.tests.remote").warning("queued")
        assert delivered.wait(timeout=1)
    finally:
        detach_logstash_logging()
