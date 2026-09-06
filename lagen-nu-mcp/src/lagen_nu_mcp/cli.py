from __future__ import annotations

import argparse
import logging
import sys

from lagen_nu_mcp.catalog import load_feeds
from lagen_nu_mcp.config import ConfigError, load_settings
from lagen_nu_mcp.fetcher import fetch_pending
from lagen_nu_mcp.http import HttpClient, RateLimiter
from lagen_nu_mcp.poller import poll_feeds
from lagen_nu_mcp.store import MemoryStore, PostgresStore, connect_postgres


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_client(settings) -> HttpClient:
    return HttpClient(
        user_agent=settings.user_agent,
        limiter=RateLimiter(settings.min_interval_seconds),
    )


def _run_poll(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(require_database=args.store == "postgres")
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    _configure_logging(settings.log_level)
    client = _build_client(settings)
    feeds = load_feeds(settings.feed_mode, client)

    if args.store == "memory":
        store = MemoryStore()
        run = poll_feeds(feeds, store=store, client=client)
        print(f"memory pending={len(store.pending)} new={run.new_total} seen={run.seen_total}")
        return 0

    assert settings.database_url is not None
    with connect_postgres(settings.database_url) as conn:
        store = PostgresStore(conn)
        run = poll_feeds(feeds, store=store, client=client)
    print(f"postgres new={run.new_total} seen={run.seen_total}")
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(require_database=args.store == "postgres")
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    _configure_logging(settings.log_level)
    client = _build_client(settings)

    if args.store == "memory":
        print("fetch --store memory needs a pending queue; use postgres for cron", file=sys.stderr)
        return 2

    assert settings.database_url is not None
    with connect_postgres(settings.database_url) as conn:
        store = PostgresStore(conn)
        run = fetch_pending(store, client, limit=args.limit)
    print(f"postgres fetched={run.fetched} failed={run.failed} rotated={run.rotated}")
    return 1 if run.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lagen-nu-mcp")
    sub = parser.add_subparsers(dest="command", required=True)

    poll = sub.add_parser("poll", help="Poll lagen.nu Atom feeds into pending_fetch")
    poll.add_argument(
        "--store",
        choices=("postgres", "memory"),
        default="postgres",
        help="postgres writes to Supabase; memory is for local sanity-checks",
    )

    fetch = sub.add_parser("fetch", help="Drain pending_fetch and cache document bodies")
    fetch.add_argument(
        "--store",
        choices=("postgres", "memory"),
        default="postgres",
    )
    fetch.add_argument("--limit", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command == "poll":
        return _run_poll(args)
    if args.command == "fetch":
        return _run_fetch(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
