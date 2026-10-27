"""Integration probe: separate owner process, two client processes, owner reads."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.services.overgraph.owner import OwnerClient

WORKER = """
import asyncio, json, sys
from pathlib import Path
from app.services.overgraph.owner import OwnerClient
async def main():
    client = OwnerClient(Path(sys.argv[1]))
    node = {"labels": ["Probe", "multiprocess"], "key": f"node-{sys.argv[2]}", "props": {"worker": sys.argv[2]}}
    response = await client.mutate(f"mutation-{sys.argv[2]}", {"upsert_nodes": [node]})
    values = await client.read([{"label": "Probe", "key": f"node-{sys.argv[2]}"}])
    print(json.dumps({"mutation": response, "read": values}))
asyncio.run(main())
"""


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="owner-mp-"))
    socket_path = root / "owner.sock"
    owner = subprocess.Popen([
        sys.executable, "-m", "app.services.overgraph.owner", str(root / "catalog"),
        "--socket", str(socket_path), "--dimension", "4",
    ])
    try:
        for _ in range(100):
            if socket_path.exists():
                break
            time.sleep(0.05)
        workers = [
            subprocess.Popen([sys.executable, "-c", WORKER, str(socket_path), worker_id], stdout=subprocess.PIPE, text=True)
            for worker_id in ("a", "b")
        ]
        outputs = [worker.communicate(timeout=60)[0] for worker in workers]
        client = OwnerClient(socket_path)
        values = asyncio.run(client.read([
            {"label": "Probe", "key": "node-a"},
            {"label": "Probe", "key": "node-b"},
        ]))
        print(json.dumps({"workers": [json.loads(item) for item in outputs], "owner_read": values}, indent=2))
        assert values["values"]["Probe:node-a"]["worker"] == "a"
        assert values["values"]["Probe:node-b"]["worker"] == "b"
        return 0
    finally:
        owner.terminate()
        owner.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
