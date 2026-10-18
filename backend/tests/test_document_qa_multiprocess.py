"""Two OS processes share one tenant file only through the lifecycle flock."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from app.services.document_qa.labels import QUESTION
from app.services.document_qa.tenants import TenantCatalogs, tenant_catalog_path, tenant_lock_path

BACKEND = Path(__file__).resolve().parents[1]
PROBE = [sys.executable, "-m", "app.services.document_qa.process_probe"]
APP = BACKEND / "app" / "services" / "document_qa"


def _run(tmp_path: Path, args: list[str], *, timeout: float = 25) -> dict:
    result = tmp_path / f"result-{time.time_ns()}.json"
    completed = subprocess.run(
        [*PROBE, *args, "--result", str(result)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload = _payload(result, completed.stderr)
    payload["returncode"] = completed.returncode
    return payload


def _popen(tmp_path: Path, args: list[str]) -> tuple[subprocess.Popen[str], Path]:
    result = tmp_path / f"hold-{time.time_ns()}.json"
    proc = subprocess.Popen(
        [*PROBE, *args, "--result", str(result)],
        cwd=BACKEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc, result


def _wait_file(path: Path, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _finish(proc: subprocess.Popen[str], result: Path, timeout: float = 20) -> dict:
    try:
        stderr = proc.communicate(timeout=timeout)[1]
    except subprocess.TimeoutExpired:
        proc.kill()
        stderr = proc.communicate()[1]
    payload = _payload(result, stderr)
    payload["returncode"] = proc.returncode
    return payload


def _payload(result: Path, stderr: str | None) -> dict:
    if result.exists():
        payload = json.loads(result.read_text())
    else:
        payload = {"ok": False, "error": (stderr or "").strip() or "no result file"}
    payload["stderr"] = (stderr or "")[-400:]
    return payload


def test_only_tenant_registry_opens_overgraph():
    leaked = [
        path.name
        for path in APP.glob("*.py")
        if path.name != "tenants.py" and "open_catalog(" in path.read_text()
    ]
    assert leaked == []
    assert tenant_lock_path(Path("/tmp/og"), 1) == Path("/tmp/og/tenants/1/tenant.lock")
    assert tenant_catalog_path(Path("/tmp/og"), 1) == Path("/tmp/og/tenants/1/knowledge")


def test_locked_handoff_keeps_both_writes(tmp_path):
    root = tmp_path / "overgraph"
    first = _run(tmp_path, ["write", "--root", str(root), "--key", "seq-a", "--text", "from-a"])
    assert first.get("ok") is True and first.get("close_error") is None
    ready_a = tmp_path / "ready-a"
    ready_b = tmp_path / "ready-b"
    waiting_b = tmp_path / "waiting-b"
    release_a = tmp_path / "release-a"
    release_b = tmp_path / "release-b"
    proc_a, result_a = _popen(tmp_path, [
        "hold", "--root", str(root), "--key", "lock-a", "--text", "writer-a",
        "--ready", str(ready_a), "--release", str(release_a),
    ])
    assert _wait_file(ready_a)
    proc_b, result_b = _popen(tmp_path, [
        "hold", "--root", str(root), "--key", "lock-b", "--text", "writer-b",
        "--ready", str(ready_b), "--release", str(release_b),
        "--waiting", str(waiting_b),
    ])
    assert _wait_file(waiting_b)
    time.sleep(0.3)
    assert ready_b.exists() is False
    release_a.write_text("go", encoding="utf-8")
    writer_a = _finish(proc_a, result_a)
    assert _wait_file(ready_b)
    release_b.write_text("go", encoding="utf-8")
    writer_b = _finish(proc_b, result_b)
    seen = _run(tmp_path, ["read", "--root", str(root), "--keys", "seq-a,lock-a,lock-b"])
    assert writer_a.get("ok") is True and writer_a.get("close_error") is None
    assert writer_b.get("ok") is True and writer_b.get("close_error") is None
    assert writer_b.get("lock_wait_ms", 0) >= 200
    assert seen["found"] == {"seq-a": True, "lock-a": True, "lock-b": True}


def test_locked_owner_then_worker(tmp_path):
    root = tmp_path / "owned"
    ready = tmp_path / "owner-ready"
    release = tmp_path / "owner-release"
    waiting = tmp_path / "worker-waiting"
    owner_proc, owner_result = _popen(tmp_path, [
        "hold", "--root", str(root), "--key", "owner-1", "--text", "api",
        "--ready", str(ready), "--release", str(release),
    ])
    assert _wait_file(ready)
    worker_proc, worker_result = _popen(tmp_path, [
        "write", "--root", str(root), "--key", "worker-1", "--text", "worker",
        "--waiting", str(waiting),
    ])
    assert _wait_file(waiting)
    time.sleep(0.3)
    assert worker_proc.poll() is None
    release.write_text("go", encoding="utf-8")
    owner = _finish(owner_proc, owner_result)
    worker = _finish(worker_proc, worker_result)
    seen = _run(tmp_path, ["read", "--root", str(root), "--keys", "owner-1,worker-1"])
    assert owner.get("ok") is True and owner.get("close_error") is None
    assert worker.get("ok") is True and worker.get("close_error") is None
    assert worker.get("lock_wait_ms", 0) >= 200
    assert seen["found"] == {"owner-1": True, "worker-1": True}


def test_lock_released_after_crash(tmp_path):
    root = tmp_path / "crash"
    ready = tmp_path / "crash-ready"
    proc, result = _popen(tmp_path, [
        "crash", "--root", str(root), "--key", "crash-1", "--text", "from-crash",
        "--ready", str(ready),
    ])
    assert _wait_file(ready)
    crashed = _finish(proc, result)
    seen = _run(tmp_path, ["read", "--root", str(root), "--keys", "crash-1"])
    assert crashed.get("action") == "crash"
    assert seen.get("ok") is True and seen.get("close_error") is None
    assert seen["found"]["crash-1"] is True
    assert seen.get("lock_wait_ms", 999) < 2000


def test_open_close_cost_and_immediate_reopen(tmp_path):
    root = tmp_path / "cost"
    first = _run(tmp_path, ["write", "--root", str(root), "--key", "cost-1", "--text", "n"])
    second = _run(tmp_path, ["write", "--root", str(root), "--key", "cost-2", "--text", "n"])
    assert first.get("ok") is True and second.get("ok") is True
    assert first.get("open_ms", 9999) < 2000
    assert first.get("close_ms", 9999) < 2000
    assert second.get("open_ms", 9999) < 2000
    tenants = TenantCatalogs(root, dimension=8)
    catalog = tenants.open_for(1)
    assert catalog.get_by_key(QUESTION, "cost-1") is not None
    tenants.close()
    again = TenantCatalogs(root, dimension=8)
    reopened = again.open_for(1)
    assert reopened.get_by_key(QUESTION, "cost-2") is not None
    again.close()
