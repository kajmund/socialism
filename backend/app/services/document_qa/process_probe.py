"""Two-process probe for one tenant OverGraph file. Not a production API."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from overgraph import OverGraphError

from app.services.document_qa.labels import QUESTION
from app.services.document_qa.tenants import TenantCatalogs

DIM = 8
VECTOR = (1.0,) + (0.0,) * 7
STORE_ERRORS = (OverGraphError, OSError, RuntimeError, ValueError, TypeError, TimeoutError)


def write_and_close(
    root: Path, key: str, text: str, *, waiting: Path | None = None,
) -> dict[str, object]:
    _mark(waiting)
    tenants = TenantCatalogs(root, dimension=DIM)
    outcome: dict[str, object] = {"ok": True, "action": "write", "key": key}
    try:
        catalog = tenants.open_for(1)
        catalog.upsert_node([QUESTION], key, props={"text": text}, dense_vector=VECTOR)
        catalog.sync()
    except STORE_ERRORS as exc:
        outcome = {"ok": False, "action": "write", "key": key, "error": _error(exc)}
    outcome.update(_timings(tenants))
    outcome.update(_close(tenants))
    return outcome


def read_keys(root: Path, keys: list[str]) -> dict[str, object]:
    tenants = TenantCatalogs(root, dimension=DIM)
    outcome: dict[str, object] = {"ok": True, "action": "read", "found": {}}
    try:
        catalog = tenants.open_for(1)
        outcome["found"] = {
            key: catalog.get_by_key(QUESTION, key) is not None for key in keys
        }
    except STORE_ERRORS as exc:
        outcome = {"ok": False, "action": "read", "error": _error(exc), "found": {}}
    outcome.update(_timings(tenants))
    outcome.update(_close(tenants))
    return outcome


def hold_write(
    root: Path,
    key: str,
    text: str,
    *,
    ready: Path,
    release: Path,
    timeout: float,
    waiting: Path | None = None,
) -> dict[str, object]:
    _mark(waiting)
    tenants = TenantCatalogs(root, dimension=DIM)
    outcome: dict[str, object] = {"ok": True, "action": "hold", "key": key}
    try:
        catalog = tenants.open_for(1)
        catalog.upsert_node([QUESTION], key, props={"text": text}, dense_vector=VECTOR)
        catalog.sync()
        ready.write_text("ready", encoding="utf-8")
        if not _wait(release, timeout):
            outcome = {"ok": False, "action": "hold", "key": key, "error": "release_timeout"}
    except STORE_ERRORS as exc:
        outcome = {"ok": False, "action": "hold", "key": key, "error": _error(exc)}
    outcome.update(_timings(tenants))
    outcome.update(_close(tenants))
    return outcome


def crash_after_sync(root: Path, key: str, text: str, ready: Path) -> dict[str, object]:
    tenants = TenantCatalogs(root, dimension=DIM)
    catalog = tenants.open_for(1)
    catalog.upsert_node([QUESTION], key, props={"text": text}, dense_vector=VECTOR)
    catalog.sync()
    ready.write_text("ready", encoding="utf-8")
    return {"ok": True, "action": "crash", "key": key, **_timings(tenants)}


def _mark(path: Path | None) -> None:
    if path is not None:
        path.write_text("waiting", encoding="utf-8")


def _wait(release: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while not release.exists():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _timings(tenants: TenantCatalogs) -> dict[str, float]:
    return {
        "lock_wait_ms": tenants.timings.lock_wait_ms,
        "open_ms": tenants.timings.open_ms,
        "close_ms": tenants.timings.close_ms,
    }


def _close(tenants: TenantCatalogs) -> dict[str, object]:
    extra: dict[str, object] = {}
    try:
        tenants.close()
    except STORE_ERRORS as exc:
        extra["close_error"] = _error(exc)
        extra["ok"] = False
    extra["close_ms"] = tenants.timings.close_ms
    return extra


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    result_path = Path(args.result)
    try:
        payload = _dispatch(args, Path(args.root))
    except STORE_ERRORS as exc:
        payload = {"ok": False, "action": args.action, "error": _error(exc)}
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    if args.action == "crash":
        os._exit(1)
    return 0 if payload.get("ok") else 1


def _dispatch(args: argparse.Namespace, root: Path) -> dict[str, object]:
    waiting = Path(args.waiting) if args.waiting else None
    if args.action == "write":
        return write_and_close(root, args.key, args.text, waiting=waiting)
    if args.action == "read":
        return read_keys(root, args.keys)
    if args.action == "crash":
        return crash_after_sync(root, args.key, args.text, Path(args.ready))
    return hold_write(
        root,
        args.key,
        args.text,
        ready=Path(args.ready),
        release=Path(args.release),
        timeout=args.timeout,
        waiting=waiting,
    )


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe one tenant OverGraph from a child process")
    parser.add_argument("action", choices=("write", "read", "hold", "crash"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--key", default="")
    parser.add_argument("--text", default="")
    parser.add_argument("--keys", default="")
    parser.add_argument("--ready", default="")
    parser.add_argument("--release", default="")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--waiting", default="")
    args = parser.parse_args(argv)
    args.keys = [item for item in args.keys.split(",") if item]
    return args


if __name__ == "__main__":
    raise SystemExit(main())
