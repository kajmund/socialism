"""Command line entrypoint for the single-writer Overgraph owner."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from app.services.overgraph.owner import OvergraphOwner


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-writer Overgraph owner")
    parser.add_argument("path", type=Path)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--dimension", type=int, default=3072)
    parser.add_argument("--max-queue", type=int, default=256)
    parser.add_argument(
        "--sync", action=argparse.BooleanOptionalAction, default=True,
        help="fsync before acknowledging a mutation (durable ack)",
    )
    parser.add_argument(
        "--read-workers", type=int, default=4,
        help="bounded read worker threads (0 keeps reads on the event loop)",
    )
    parser.add_argument("--profile-lag", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile-locks", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--lock-mode", choices=("global", "read_write"), default="global",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    async def run() -> None:
        owner = OvergraphOwner(
            args.path, dimension=args.dimension, socket_path=args.socket,
            max_queue=args.max_queue, sync_on_commit=args.sync,
        )
        owner.profile_lag = args.profile_lag
        owner.profile_locks = args.profile_locks
        owner.lock_mode = args.lock_mode
        owner.read_workers = max(0, args.read_workers)
        await owner.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(signum, stop.set)
            except NotImplementedError:  # pragma: no cover - Windows
                pass
        print(json.dumps({"ready": True, "socket": str(args.socket)}), flush=True)
        try:
            await stop.wait()
        finally:
            await owner.close()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
