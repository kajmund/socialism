"""Verify one saved answer with real Graph v2, embedding cache and configured assessor."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path


async def run(args):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
    from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
    from tests.research_reuse.sufficient_live import repeat, selected_workload

    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0, pool_timeout=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        need, context, metadata = await selected_workload(
            factory, args.attempt_id, args.need_id, as_main=args.as_main,
        )
        # A new cache instance per invocation keeps repeated CLI checks honest.
        embeddings = GraphEmbeddingCacheProvider(factory, OpenAIEmbeddingProvider.from_settings())
        results = await repeat(factory, need, context, embeddings, count=args.repeat)
        output = {
            "mode": "live", "attempt_id": args.attempt_id, "need": asdict(need),
            "scope": asdict(context.scope), "configuration": metadata, "iterations": results,
            "contract_passed": all(row["contract_passed"] for row in results),
        }
        with Path(args.output).open("x", encoding="utf-8") as target:
            json.dump(output, target, ensure_ascii=False, indent=2)
        print(json.dumps({
            "question": need.question, "contract_passed": output["contract_passed"],
            "iterations": [
                {key: row[key] for key in ("checks", "seconds", "timings", "answer_fact_ids")}
                for row in results
            ],
        }, ensure_ascii=False, indent=2))
        return int(not output["contract_passed"])
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--need-id", help="Select a saved subquestion; omit for original main")
    parser.add_argument("--as-main", action="store_true", help="Assess selected subquestion as main")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", required=True, help="New report file")
    args = parser.parse_args()
    if args.as_main and not args.need_id:
        parser.error("--as-main requires --need-id")
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    if Path(args.output).exists():
        parser.error("output file already exists")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
