"""Audit and cleanup the durable knowledge graph.

python -m app.services.knowledge.audit_cli audit
python -m app.services.knowledge.audit_cli cleanup
python -m app.services.knowledge.audit_cli cleanup --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.database.session import SessionLocal, engine
from app.services.knowledge.audit import audit_knowledge_graph, cleanup_knowledge_graph


async def run(args: argparse.Namespace) -> object:
    async with SessionLocal() as session:
        if args.action == "audit":
            report = await audit_knowledge_graph(session)
            return report.as_dict()
        payload = await cleanup_knowledge_graph(session, apply=args.apply)
        if args.apply:
            await session.commit()
        return payload


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("audit")
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument(
        "--apply",
        action="store_true",
        help="Rewire references and remove duplicates. Default is dry-run.",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(await run(args), ensure_ascii=False, default=str))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
