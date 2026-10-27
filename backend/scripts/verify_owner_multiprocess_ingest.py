"""Two real processes through one owner: TextUnit ingest, owner restart, embedding."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.services.overgraph.owner import OwnerClient

INGEST = """
import asyncio, json, sys
from pathlib import Path
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_writer import write_text_units_via_owner

async def main():
    scope = customer_scope(1)
    units = []
    for index in range(100):
        text = f"Klausul {index}: uppsägningstid."
        units.append(TextUnit(
            id=f"mp-unit-{index}", document_version_id="mp-ver-1", document_id="mp-doc-1",
            section_id="mp-sec-1", ordinal=index, text=text, content_hash=hash_text(text),
            locator=f"stycke {index + 1}", page_start=index // 10 + 1, page_end=index // 10 + 1,
            char_start=index * 20, char_end=index * 20 + len(text),
        ))
    client = OwnerClient(Path(sys.argv[1]))
    result = await write_text_units_via_owner(
        client, units, scope=scope, embeddings=[None for _ in units],
        section_titles={"mp-sec-1": "Avtal"}, section_ordinals={"mp-sec-1": 0},
    )
    print(json.dumps({"result": result, "ids": [unit.id for unit in units]}))

asyncio.run(main())
"""

EMBED = """
import asyncio, json, sys
from pathlib import Path
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_writer import write_text_unit_embeddings_via_owner

async def main():
    client = OwnerClient(Path(sys.argv[1]))
    ids = [f"mp-unit-{index}" for index in range(100)]
    values = await client.read([{"label": "TextUnit", "key": key} for key in ids])
    units = []
    for key in ids:
        props = values["values"][f"TextUnit:{key}"]
        units.append(TextUnit(
            id=key, document_version_id=props["document_version_id"], document_id=props["document_id"],
            section_id=props["section_id"] or None, ordinal=props["ordinal"], text=props["text"],
            content_hash=props["content_hash"], locator=props["locator"], page_start=props["page_start"],
            page_end=props["page_end"], char_start=props["char_start"], char_end=props["char_end"],
        ))
    result = await write_text_unit_embeddings_via_owner(
        client, units, [[float(index), 0.0, 0.0, 0.0] for index in range(100)],
        mutation_id="mp-embeddings-1",
    )
    print(json.dumps({"result": result}))

asyncio.run(main())
"""


def _owner(path: Path, socket: Path) -> subprocess.Popen[str]:
    return subprocess.Popen([
        sys.executable, "-m", "app.services.overgraph.owner", str(path),
        "--socket", str(socket), "--dimension", "4",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _wait_socket(socket: Path) -> None:
    for _ in range(200):
        if socket.exists():
            return
        time.sleep(0.05)
    raise RuntimeError("owner socket did not appear")


def _worker(code: str, socket: Path) -> dict:
    process = subprocess.run([sys.executable, "-c", code, str(socket)], capture_output=True, text=True, timeout=90)
    if process.returncode != 0:
        raise RuntimeError(process.stderr)
    return json.loads(process.stdout)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="owner-mp-ingest-"))
    socket = root / "owner.sock"
    catalog = root / "catalog"
    owner = _owner(catalog, socket)
    try:
        _wait_socket(socket)
        ingest = _worker(INGEST, socket)
        assert ingest["result"]["ok"] is True
        assert len(ingest["ids"]) == 100
        # Restart the owner between ingest and embedding; the client must reconnect.
        owner.terminate()
        owner.wait(timeout=10)
        owner = _owner(catalog, socket)
        _wait_socket(socket)
        embed = _worker(EMBED, socket)
        assert embed["result"]["ok"] is True
        read = asyncio.run(OwnerClient(socket).read([
            {"label": "TextUnit", "key": "mp-unit-0"},
            {"label": "TextUnit", "key": "mp-unit-99"},
        ]))
        assert read["values"]["TextUnit:mp-unit-0"]["content_hash"]
        print(json.dumps({"ingest": ingest["result"], "embed": embed["result"], "read": read}, indent=2))
        return 0
    finally:
        owner.terminate()
        owner.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
